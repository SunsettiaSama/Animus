from __future__ import annotations

_MEMORY_HEADER = "【可能相关的记忆】"
_MEMORY_NOTE = (
    "在你开口说话时，心底会自然浮现出下面这些记忆片段；"
    "有的可靠、与当下贴切，有的则完全无关或朦胧错位。"
    "不必逐条回应，也不必强行塞进对白——只取那些真正在心头撞上的。"
)


def render_similar_memories_block(lines: list[str]) -> str:
    cleaned = [line.strip() for line in lines if line.strip()]
    if not cleaned:
        return ""
    body = "\n".join(f"- {line}" for line in cleaned)
    return f"{_MEMORY_HEADER}\n{_MEMORY_NOTE}\n{body}"
