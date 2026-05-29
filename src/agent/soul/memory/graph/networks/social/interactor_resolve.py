from __future__ import annotations

from dataclasses import dataclass

from agent.soul.memory.domain.enums import MemoryNetwork, SocialNodeRole
from agent.soul.memory.graph.networks.social.node import SocialCoreNode

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.soul.memory.graph.networks.social.network import SocialMemoryNetwork


def render_interactor_portrait_block(interactor_id: str, core: SocialCoreNode) -> str:
    name = core.portrait.name.strip()
    header = f"交互者：{name}（{interactor_id}）" if name else f"交互者：{interactor_id}"
    lines = ["【对话者画像】", header]
    body = core.portrait.render().strip()
    if body:
        lines.append(body)
    relation = core.agent_relation.strip()
    if relation:
        lines.append(f"Agent 主观关系：{relation}")
    changelog = core.trait_changelog.strip()
    if changelog:
        tail = changelog.splitlines()[-1].strip()
        if tail:
            lines.append(f"近期印象：{tail}")
    return "\n".join(lines)


@dataclass(frozen=True)
class InteractorProbeResult:
    interactor_id: str
    core: SocialCoreNode | None
    ambiguous: bool
    best_score: float = 0.0
    second_score: float = 0.0


def _collect_interactor_scores(
    social: "SocialMemoryNetwork",
    text: str,
    *,
    top_k: int,
) -> list[tuple[str, SocialCoreNode, float]]:
    scored = social._query.recall(text, top_k=top_k, interactor_id="")
    ranked: list[tuple[str, SocialCoreNode, float]] = []
    seen: set[str] = set()

    for item in scored:
        unit = item.unit
        if isinstance(unit, SocialCoreNode):
            iid = unit.interactor_id.strip()
            core = unit
        else:
            iid = getattr(unit, "interactor_id", "").strip()
            core = social._nodes.get_core_for_interactor(iid)
            if not isinstance(core, SocialCoreNode):
                continue
        if not iid or iid in seen:
            continue
        seen.add(iid)
        ranked.append((iid, core, float(item.final_score)))

    ranked.sort(key=lambda row: row[2], reverse=True)
    return ranked


def probe_interactor_core(
    social: "SocialMemoryNetwork",
    query: str,
    *,
    hinted_interactor_id: str = "",
    top_k: int = 12,
    min_best_score: float = 0.12,
    max_score_gap: float = 0.20,
) -> InteractorProbeResult:
    """试探性检索：分数差距过小视为歧义，返回 ambiguous=True（空画像，防污染）。"""
    hinted = hinted_interactor_id.strip()
    if hinted:
        core = social._nodes.get_core_for_interactor(hinted)
        if isinstance(core, SocialCoreNode):
            return InteractorProbeResult(
                interactor_id=hinted,
                core=core,
                ambiguous=False,
                best_score=1.0,
                second_score=0.0,
            )

    text = query.strip()
    if not text:
        return InteractorProbeResult("", None, ambiguous=False)

    ranked = _collect_interactor_scores(social, text, top_k=top_k)
    if not ranked:
        pool = social._nodes.list_by_network(MemoryNetwork.social, limit=200)
        for node in pool:
            if not isinstance(node, SocialCoreNode):
                continue
            iid = node.interactor_id.strip()
            if not iid:
                continue
            hay = node.embed_text().lower()
            if any(token in hay for token in text.lower().split() if len(token) >= 2):
                return InteractorProbeResult(iid, node, ambiguous=False, best_score=0.5, second_score=0.0)
        return InteractorProbeResult("", None, ambiguous=False)

    best_id, best_core, best_score = ranked[0]
    second_score = ranked[1][2] if len(ranked) > 1 else 0.0
    gap = best_score - second_score

    if best_score < min_best_score:
        return InteractorProbeResult("", None, ambiguous=True, best_score=best_score, second_score=second_score)
    if len(ranked) > 1 and gap < max_score_gap:
        return InteractorProbeResult("", None, ambiguous=True, best_score=best_score, second_score=second_score)

    return InteractorProbeResult(
        interactor_id=best_id,
        core=best_core,
        ambiguous=False,
        best_score=best_score,
        second_score=second_score,
    )


def resolve_likely_interactor_core(
    social: "SocialMemoryNetwork",
    query: str,
    *,
    hinted_interactor_id: str = "",
    top_k: int = 12,
) -> tuple[str, SocialCoreNode | None]:
    """按用户语气/文本在 social 网中推断最可能的交互者，并返回其核心节点。"""
    probe = probe_interactor_core(
        social,
        query,
        hinted_interactor_id=hinted_interactor_id,
        top_k=top_k,
    )
    if probe.ambiguous:
        return "", None
    return probe.interactor_id, probe.core
