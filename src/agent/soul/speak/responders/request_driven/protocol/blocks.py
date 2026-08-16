from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

RoleBlockKind = Literal[
    "speak",
    "think",
    "speak_action",
    "speak_context",
    "body_action",
    "ask_help",
    "note_director",
    "note_screenwriter",
    "unknown",
]

# 角色协议：只认成对标签；残片/裸文本填入 speak 字段，不另造 body。
_ANY_BLOCK_RE = re.compile(
    r"(?:"
    r"\[think\](.*?)\[/think\]"
    r"|<(speak|speak\s+action|speak\s+context|body\s+action|ask\s+help|note\s+director|note\s+screenwriter)\s*>(.*?)</\s*\2\s*>"
    r"|\[(speak_action|speak_context|body_action|think|ask_help|note_director|note_screenwriter)\s*:\s*(.*?)]"
    r")",
    re.IGNORECASE | re.DOTALL,
)

_ROLE_TAG_DEBRIS_RE = re.compile(
    r"</?\s*(?:body\s+action|speak(?:\s+action|\s+context)?|think|"
    r"ask\s+help|note\s+director|note\s+screenwriter)\s*>",
    re.IGNORECASE,
)
_COMPOSE_PAIR_RE = re.compile(
    r"\[(think|speak|action|state|recall)\](.*?)\[/\1\]",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class RoleBlock:
    kind: RoleBlockKind
    content: str
    raw_tag: str = ""


def strip_role_tag_debris(text: str) -> str:
    """去掉角色协议标签残片，只留可读正文。"""
    cleaned = _ROLE_TAG_DEBRIS_RE.sub("", str(text or ""))
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def parse_role_blocks(raw: str) -> list[RoleBlock]:
    text = raw or ""
    blocks = list(_scan_any(text))
    if blocks:
        return blocks
    stripped = strip_role_tag_debris(text)
    if not stripped:
        return []
    return [RoleBlock(kind="speak_context", content=stripped, raw_tag="plain")]


def _normalize_tag(tag: str) -> RoleBlockKind:
    key = re.sub(r"\s+", " ", tag.strip().lower())
    if key == "speak":
        return "speak"
    if key in ("think",):
        return "think"
    if key in ("speak context", "speak_context"):
        return "speak_context"
    if key in ("body action", "body_action"):
        return "body_action"
    if key in ("speak action", "speak_action"):
        return "speak_action"
    if key in ("ask help", "ask_help"):
        return "ask_help"
    if key in ("note director", "note_director"):
        return "note_director"
    if key in ("note screenwriter", "note_screenwriter"):
        return "note_screenwriter"
    return "unknown"


def _append_plain_speak(blocks: list[RoleBlock], gap: str) -> None:
    cleaned = strip_role_tag_debris(gap)
    cleaned = _COMPOSE_PAIR_RE.sub("", cleaned).strip()
    if not cleaned:
        return
    if blocks and blocks[-1].kind == "body_action" and blocks[-1].content == cleaned:
        return
    blocks.append(RoleBlock(kind="speak", content=cleaned, raw_tag="plain"))


def _scan_any(text: str) -> list[RoleBlock]:
    blocks: list[RoleBlock] = []
    cursor = 0
    for match in _ANY_BLOCK_RE.finditer(text):
        _append_plain_speak(blocks, text[cursor : match.start()])
        if match.group(1) is not None:
            content = (match.group(1) or "").strip()
            if content:
                blocks.append(RoleBlock(kind="think", content=content, raw_tag="think"))
        elif match.group(2) is not None:
            tag = match.group(2)
            content = (match.group(3) or "").strip()
            blocks.append(RoleBlock(kind=_normalize_tag(tag), content=content, raw_tag=tag))
        elif match.group(4) is not None:
            tag = match.group(4)
            content = (match.group(5) or "").strip()
            blocks.append(RoleBlock(kind=_normalize_tag(tag), content=content, raw_tag=tag))
        cursor = match.end()
    _append_plain_speak(blocks, text[cursor:])
    return blocks
