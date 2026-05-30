from __future__ import annotations

_WM_HEADER = "【当前会话·工作记忆】"
_WM_NOTE = (
    "以下为当前 session 内、本 generation 的对话上下文；"
    "上方为已完成的蒸馏摘要，下方为尚未蒸馏的最近轮次原文。"
    "仅用于理解当下对白，不要与长期涌现记忆混淆。"
)


def render_dialogue_compressed(sentences: list[str]) -> str:
    """内部 probe 用：已完成蒸馏的单句摘要（无 prompt 头）。"""
    lines = [part.strip() for part in sentences if part.strip()]
    if not lines:
        return ""
    return "\n".join(f"- {line}" for line in lines)


def render_session_working_memory(
    *,
    generation: int,
    distilled: list[str],
    recent_turns: list[tuple[str, str]],
) -> str:
    """当前 generation 工作记忆块（蒸馏摘要 + 未蒸馏 verbatim）。"""
    distilled_lines = [part.strip() for part in distilled if part.strip()]
    recent_parts: list[str] = []
    for user_text, agent_text in recent_turns:
        user = user_text.strip()
        agent = agent_text.strip()
        if user:
            recent_parts.append(f"用户：{user}")
        if agent:
            recent_parts.append(f"我：{agent}")
    if not distilled_lines and not recent_parts:
        return ""
    sections: list[str] = [
        _WM_HEADER,
        _WM_NOTE,
        f"generation={generation}",
    ]
    if distilled_lines:
        sections.append("已蒸馏摘要：")
        sections.extend(f"- {line}" for line in distilled_lines)
    if recent_parts:
        sections.append("最近轮次（原文）：")
        sections.extend(recent_parts)
    return "\n".join(sections)


def normalize_one_sentence(text: str, *, max_chars: int = 240) -> str:
    """蒸馏结果规范化：仅保留一句。"""
    normalized = text.strip()
    if not normalized:
        return ""
    normalized = normalized.splitlines()[0].strip()
    normalized = " ".join(normalized.split())
    if not normalized:
        return ""
    for sep in ("。", "！", "？", ".", "!", "?"):
        if sep in normalized:
            head, _ = normalized.split(sep, 1)
            normalized = head + sep if sep in "。！？" else head + "."
            break
    normalized = normalized.strip(' "\'')
    if max_chars > 0 and len(normalized) > max_chars:
        normalized = normalized[:max_chars].rstrip()
    return normalized
