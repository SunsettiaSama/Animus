from __future__ import annotations

_MEMORY_HEADER = "【涌现记忆·长期】"
_MEMORY_NOTE = (
    "以下为你开口时从记忆系统中涌现、检索到的片段；"
    "属于长期记忆，不是当前对话原文，也不是上方工作记忆。"
    "不必逐条回应，也不必强行塞进对白——只取那些真正在心头撞上的。"
)


def render_similar_memories_block(lines: list[str]) -> str:
    cleaned = [line.strip() for line in lines if line.strip()]
    if not cleaned:
        return ""
    body = "\n".join(f"- {line}" for line in cleaned)
    return f"{_MEMORY_HEADER}\n{_MEMORY_NOTE}\n{body}"
