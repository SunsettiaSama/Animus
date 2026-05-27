from __future__ import annotations

from .model import SpeakAgentOutput, SpeakSessionState
from .tags import iter_tag_blocks


def _normalize_session_state(value: str) -> SpeakSessionState:
    normalized = value.strip().lower()
    if normalized == "append":
        return "append"
    if normalized == "share":
        return "share"
    if normalized == "recall":
        return "recall"
    return "finish"


def parse_agent_output(raw: str) -> SpeakAgentOutput:
    """解析 Speak agent 原始输出 → 结构化字段。"""
    blocks = tuple(iter_tag_blocks(raw))
    if not blocks:
        return SpeakAgentOutput(raw=raw)

    thinks: list[str] = []
    speaks: list[str] = []
    actions: list[str] = []
    recall_queries: list[str] = []
    session_state: SpeakSessionState = "finish"
    anchor_tool = ""
    observe = ""

    for block in blocks:
        if block.kind == "think" and block.content:
            thinks.append(block.content)
        elif block.kind == "speak" and block.content:
            speaks.append(block.content)
        elif block.kind == "action" and block.content:
            actions.append(block.content)
        elif block.kind == "recall" and block.content:
            recall_queries.append(block.content)
        elif block.kind == "state" and block.content:
            session_state = _normalize_session_state(block.content)
        elif block.kind == "anchor" and block.content:
            anchor_tool = block.content
        elif block.kind == "observe" and block.content:
            observe = block.content

    recall_query = recall_queries[0] if recall_queries else ""
    if session_state == "recall" and not recall_query:
        recall_query = speaks[-1] if speaks else thinks[-1] if thinks else ""

    return SpeakAgentOutput(
        thought="\n".join(thinks),
        speak="".join(speaks),
        actions=tuple(actions),
        session_state=session_state,
        recall_query=recall_query,
        anchor_tool=anchor_tool,
        observe=observe,
        blocks=blocks,
        raw=raw,
    )
