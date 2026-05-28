from __future__ import annotations

SPEAK_TAG_NAMES: tuple[str, ...] = (
    "think",
    "speak",
    "action",
    "state",
    "recall",
    "anchor",
    "observe",
)

# 解析保留、但不向前端推送的 tag
FRONTEND_SUPPRESSED_TAGS: frozenset[str] = frozenset({"think"})


def speak_tag(kind: str, content: str = "...") -> str:
    return f"[{kind}:{content}]"
