from __future__ import annotations

SPEAK_TAG_NAMES: tuple[str, ...] = (
    "think",
    "speak",
    "action",
    "state",
    "anchor",
    "observe",
)


def speak_tag(kind: str, content: str = "...") -> str:
    return f"[{kind}:{content}]"
