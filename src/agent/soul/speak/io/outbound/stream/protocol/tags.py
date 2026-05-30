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


def speak_tag_open(kind: str) -> str:
    return f"[{kind}]"


def speak_tag_close(kind: str) -> str:
    return f"[/{kind}]"


def speak_tag_pair(kind: str, inner: str = "...") -> str:
    """成对 bracket 标签（XML 式），如 [speak]…[/speak]。"""
    return f"{speak_tag_open(kind)}{inner}{speak_tag_close(kind)}"


def speak_tag(kind: str, inner: str = "...") -> str:
    return speak_tag_pair(kind, inner)
