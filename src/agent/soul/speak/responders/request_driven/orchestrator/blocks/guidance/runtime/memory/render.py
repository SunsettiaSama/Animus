from __future__ import annotations

_MEMORY_LEAD = (
    "以下几段从长期记忆里浮现，属于过往经历而非当前对白原文；"
    "不必逐条回应，只取那些真正在心头撞上的。"
)


def render_similar_memories_block(lines: list[str]) -> str:
    cleaned = [line.strip() for line in lines if line.strip()]
    if not cleaned:
        return ""
    body = "\n".join(f"- {line}" for line in cleaned)
    return f"{_MEMORY_LEAD}\n{body}"
