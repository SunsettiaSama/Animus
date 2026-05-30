from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage, SystemMessage

from agent.soul.memory.domain.enums import MemoryNetwork, Valence
from agent.soul.memory.graph.base_node import BaseNode

from agent.soul.memory.graph.networks.event.node import FactualMemory
from agent.soul.memory.graph.networks.social.node import SocialNeighborhoodNode
from agent.soul.memory.embed_text import memory_unit_embed_text
from agent.soul.memory.emotion_intensity import infer_emotion_intensity

from agent.soul.memory.graph.networks.experience_block import ExperienceBlock
from agent.soul.memory.graph.networks.types import ArchivePlacement, ArchiveResult, ExperienceKind, SemanticCandidate

if TYPE_CHECKING:
    from infra.llm import BaseLLM

    from agent.soul.memory.graph.node_store import GraphNodeStore
    from agent.soul.memory.ports import VectorIndexPort


_SYSTEM = """\
你是记忆归档系统：把 Life 体验单元写入记忆图。
归档须与给定的 Agent 人格锚点一致，用该角色的第一人称主观语气归纳；
勿写成泛化 AI、系统助手或「数据流/界面」式元叙事，除非体验原文明确如此。

输出字段：
- subjective_statement: 主观陈述，<=80 字，第一人称
- focus: 核心主题，<=12 字
- label: 社交补充标签，<=12 字（仅 anchor 类）
- parent_node_id: 语义父节点 id，无则 "none"
- parent_reason: 关联理由
- emotion: 情绪名
- valence: "positive" | "negative" | "mixed" | "neutral"
- base_activation: 0.3~0.9

只输出合法 JSON，不要解释。"""

_SCHEMA = """\
{
  "focus": "",
  "subjective_statement": "",
  "label": "",
  "parent_node_id": "none",
  "parent_reason": "",
  "emotion": "",
  "valence": "neutral",
  "base_activation": 0.6
}"""


@dataclass
class ArchivalConfig:
    candidate_k: int = 5
    min_similarity: float = 0.20
    fallback_limit: int = 8


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return json.loads(m.group())
    raise ValueError(f"LLM ???????? JSON?{raw[:200]}")


def _valence(raw: str, block: ExperienceBlock) -> Valence:
    text = raw.strip().lower()
    if text in {v.value for v in Valence}:
        return Valence(text)
    vd = block.valence_delta
    if vd > 0.15:
        return Valence.positive
    if vd < -0.15:
        return Valence.negative
    return Valence.neutral


def _render_node(node: BaseNode, score: float) -> str:
    chunks = [f"[{node.MEMORY_TYPE}] {node.focus}"]
    for attr in ("fact", "perception", "reconstructed_fact", "narrative", "content", "label"):
        val = getattr(node, attr, "")
        if val:
            chunks.append(str(val)[:100])
            break
    return f"id={node.id} score={score:.3f} " + " | ".join(chunks)


class ExperienceArchiver:
    """???? + LLM ???????? + ???????"""

    def __init__(
        self,
        llm: BaseLLM,
        nodes: GraphNodeStore,
        *,
        vectors: VectorIndexPort | None = None,
        cfg: ArchivalConfig | None = None,
    ) -> None:
        self._llm = llm
        self._nodes = nodes
        self._vectors = vectors
        self._cfg = cfg or ArchivalConfig()

    def archive_event(
        self,
        block: ExperienceBlock,
        *,
        agent_persona_narrative: str = "",
    ) -> ArchiveResult:
        candidates = self._semantic_candidates(
            block.raw_text,
            MemoryNetwork.event,
            interactor_id=block.interactor_id,
        )
        placement = self._llm_place(
            block,
            candidates,
            inject_kind=ExperienceKind.event,
            agent_persona_narrative=agent_persona_narrative,
        )
        node = self._build_event_node(block, placement)
        return ArchiveResult(
            node=node,
            parent_node_id=placement.parent_node_id,
            parent_reason=placement.parent_reason,
            candidates=candidates,
        )

    def archive_anchor(
        self,
        block: ExperienceBlock,
        *,
        agent_persona_narrative: str = "",
    ) -> ArchiveResult:
        candidates = self._semantic_candidates(
            block.raw_text,
            MemoryNetwork.social,
            interactor_id=block.interactor_id,
        )
        placement = self._llm_place(
            block,
            candidates,
            inject_kind=ExperienceKind.anchor,
            agent_persona_narrative=agent_persona_narrative,
        )
        node = self._build_anchor_node(block, placement)
        return ArchiveResult(
            node=node,
            parent_node_id=placement.parent_node_id,
            parent_reason=placement.parent_reason,
            candidates=candidates,
        )

    def _semantic_candidates(
        self,
        raw_text: str,
        network: MemoryNetwork,
        *,
        interactor_id: str = "",
    ) -> list[SemanticCandidate]:
        text = raw_text.strip()
        if not text:
            return []

        hits: list[tuple[str, float]] = []
        if self._vectors is not None:
            vector = self._vectors.embed_query(text)
            if vector:
                hits = self._vectors.search(
                    vector,
                    top_k=self._cfg.candidate_k * 2,
                    network=network,
                )

        if not hits:
            recent = self._nodes.list_recent(
                network=network,
                limit=self._cfg.fallback_limit,
            )
            if interactor_id:
                recent = [
                    n for n in recent
                    if not n.interactor_id or n.interactor_id == interactor_id
                ]
            return [
                SemanticCandidate(
                    node_id=n.id,
                    score=0.5,
                    render=_render_node(n, 0.5),
                )
                for n in recent[: self._cfg.candidate_k]
            ]

        score_map = {
            uid: score
            for uid, score in hits
            if score >= self._cfg.min_similarity
        }
        if not score_map:
            score_map = dict(hits[: self._cfg.candidate_k])

        nodes = self._nodes.get_many(list(score_map.keys()))
        if interactor_id:
            nodes = [
                n for n in nodes
                if not n.interactor_id or n.interactor_id == interactor_id
            ]

        ranked = sorted(
            nodes,
            key=lambda n: score_map.get(n.id, 0.0),
            reverse=True,
        )
        out: list[SemanticCandidate] = []
        for node in ranked[: self._cfg.candidate_k]:
            score = score_map.get(node.id, 0.0)
            out.append(
                SemanticCandidate(
                    node_id=node.id,
                    score=score,
                    render=_render_node(node, score),
                )
            )
        return out

    def _llm_place(
        self,
        block: ExperienceBlock,
        candidates: list[SemanticCandidate],
        *,
        inject_kind: ExperienceKind,
        agent_persona_narrative: str = "",
    ) -> ArchivePlacement:
        if candidates:
            candidate_lines = "\n".join(
                f"{i + 1}. {c.render}" for i, c in enumerate(candidates)
            )
        else:
            candidate_lines = "（无候选父节点，parent_node_id 填 none）"

        kind_label = "社交/锚点" if inject_kind == ExperienceKind.anchor else "事件事实"
        persona_section = ""
        persona = agent_persona_narrative.strip()
        if persona:
            persona_section = (
                f"\n【Agent 人格锚点（归档语气须与此一致）】\n{persona}\n"
            )
        prompt = (
            f"体验 id：{block.experience_id}\n"
            f"来源：{block.source}\n"
            f"写入类型：{kind_label}\n"
            f"体验原文：\n{block.raw_text}\n"
            f"情绪线索：{block.emotion_label or '（未标注）'} "
            f"显著性={block.salience:.2f}\n"
            f"{persona_section}\n"
            f"语义候选父节点：\n{candidate_lines}\n\n"
            f"输出 JSON：\n{_SCHEMA}"
        )
        raw = self._llm.generate_messages(
            [SystemMessage(content=_SYSTEM), HumanMessage(content=prompt)]
        )
        d = _extract_json(raw)
        parent_raw = str(d.get("parent_node_id", "none")).strip()
        valid_ids = {c.node_id for c in candidates}
        parent_id = parent_raw if parent_raw in valid_ids else None
        label = str(d.get("label", "")).strip()
        if not label and inject_kind == ExperienceKind.anchor:
            label = str(d.get("focus", "")).strip()[:12]
        subjective = str(d.get("subjective_statement", block.raw_text)).strip()
        emotion = str(d.get("emotion", block.emotion_label)).strip()
        return ArchivePlacement(
            focus=str(d.get("focus", block.raw_text[:12])).strip()[:60],
            subjective_statement=subjective,
            parent_node_id=parent_id,
            parent_reason=str(d.get("parent_reason", "")).strip(),
            emotion=emotion,
            emotion_intensity=infer_emotion_intensity(
                emotion,
                subjective,
                block.raw_text,
            ),
            valence=_valence(str(d.get("valence", "neutral")), block).value,
            base_activation=float(d.get("base_activation", max(0.3, block.salience))),
            label=label,
        )

    def _build_event_node(
        self,
        block: ExperienceBlock,
        placement: ArchivePlacement,
    ) -> FactualMemory:
        return FactualMemory(
            focus=placement.focus or block.raw_text[:60],
            fact=block.raw_text,
            perception=placement.subjective_statement,
            emotion=placement.emotion or block.emotion_label,
            emotion_intensity=placement.emotion_intensity,
            valence=Valence(placement.valence),
            base_activation=placement.base_activation,
            interactor_id=block.interactor_id,
            life_event_id=block.experience_id,
            meta={
                "life_event_id": block.experience_id,
                "experience_source": block.source,
                "archive_parent_reason": placement.parent_reason,
            },
        )

    def _build_anchor_node(
        self,
        block: ExperienceBlock,
        placement: ArchivePlacement,
    ) -> SocialNeighborhoodNode:
        label = placement.label or placement.focus or "补充信息"
        content = placement.subjective_statement or block.raw_text
        return SocialNeighborhoodNode(
            interactor_id=block.interactor_id,
            focus=placement.focus or label[:60],
            label=label[:200],
            content=content,
            emotion=placement.emotion or block.emotion_label,
            emotion_intensity=placement.emotion_intensity,
            valence=Valence(placement.valence),
            base_activation=placement.base_activation,
            meta={
                "life_event_id": block.experience_id,
                "experience_source": block.source,
                "archive_parent_reason": placement.parent_reason,
            },
        )


def node_embed_text(node: BaseNode) -> str:
    if hasattr(node, "embed_text"):
        return node.embed_text()
    return memory_unit_embed_text(node)
