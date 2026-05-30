from __future__ import annotations

from agent.soul.speak.io.outbound.stream.parse.tags import SpeakTagBlock

_ACTION_PREFIX = "（动作）"


def format_agent_turn_for_working_memory(
    blocks: tuple[SpeakTagBlock, ...],
    *,
    speak_fallback: str = "",
) -> str:
    """按 LLM 输出标签顺序拼接 speak/action，供对话工作记忆与蒸馏使用。"""
    lines: list[str] = []
    for block in blocks:
        content = block.content.strip()
        if not content:
            continue
        if block.kind == "action":
            lines.append(f"{_ACTION_PREFIX}{content}")
        elif block.kind == "speak":
            lines.append(content)
    if not lines and speak_fallback.strip():
        lines.append(speak_fallback.strip())
    return "\n".join(lines)
