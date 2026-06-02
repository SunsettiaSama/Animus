from __future__ import annotations

from agent.soul.memory.graph.networks.social.node import SocialCoreNode


def _trait_clause(core_traits: list[str]) -> str:
    cleaned = [t.strip() for t in core_traits if t.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return f"性情{cleaned[0]}"
    return "性情" + "、".join(cleaned[:4])


def _identity_clause(core: SocialCoreNode) -> str:
    name = core.portrait.name.strip()
    traits = _trait_clause(list(core.portrait.core_traits))
    bg_facts = [b.strip() for b in core.portrait.background_facts if b.strip()]
    if bg_facts:
        role = bg_facts[0]
        if traits:
            return f"作为{role}，{name or '对方'}{traits}。"
        return f"作为{role}，{name or '对方'}是你此刻交谈的人。"
    if traits:
        return f"{name or '对方'}是{traits}的人。"
    if name:
        return f"{name}是你此刻交谈的人。"
    return ""


def _snippets_clause(snippets: tuple[str, ...]) -> str:
    if not snippets:
        return ""
    parts: list[str] = []
    for text in snippets[:2]:
        line = text.strip().rstrip("。．.")
        if not line:
            continue
        if line.startswith("你记得") or line.startswith("你想起"):
            parts.append(line + "。")
        else:
            parts.append(f"你记得{line}。")
    return "".join(parts)


def render_interactor_opening_narrative(
    *,
    interactor_id: str,
    core: SocialCoreNode,
    neighborhood_snippets: tuple[str, ...] = (),
    user_text: str = "",
    agent_relation: str = "",
    recent_impression: str = "",
) -> str:
    """第二人称叙述：自然衔接「对方与你」及画像要点（供 Speak persona 注入）。"""
    name = core.portrait.name.strip() or interactor_id.strip() or "对方"
    lines: list[str] = []

    if user_text.strip():
        lines.append(f"现在，{name}和你发起了对话。")
    else:
        lines.append(f"现在，你正在与{name}交谈。")

    identity = _identity_clause(core)
    if identity:
        lines.append(identity)

    snippet_text = _snippets_clause(neighborhood_snippets)
    if snippet_text:
        lines.append(snippet_text)

    relation = agent_relation.strip()
    if relation:
        if relation.startswith("你") or "你" in relation[:6]:
            lines.append(relation.rstrip("。．.") + "。")
        else:
            lines.append(f"在你看来，{relation.rstrip('。．.')}。")

    impression = recent_impression.strip()
    if impression and impression not in "\n".join(lines):
        lines.append(f"你最近对{name}的印象是：{impression.rstrip('。．.')}。")

    return "".join(lines)
