from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

RoleBlockKind = Literal[
    "think",
    "speak_action",
    "speak_context",
    "body_action",
    "ask_help",
    "unknown",
]

_ANY_BLOCK_RE = re.compile(
    r"(?:"
    r"\[think\](.*?)\[/think\]"
    r"|<(speak\s+action|speak\s+context|body\s+action|ask\s+help)\s*>(.*?)</\s*\2\s*>"
    r"|<(speak\s+action|speak\s+context|body\s+action|ask\s+help)\s*>\s*([^<\n]+)"
    r"|\[(speak_action|speak_context|body_action|think|ask_help)\s*:\s*(.*?)]"
    r")",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class RoleBlock:
    kind: RoleBlockKind
    content: str
    raw_tag: str = ""


def parse_role_blocks(raw: str) -> list[RoleBlock]:
    text = raw or ""
    blocks = list(_scan_any(text))
    if blocks:
        return blocks
    stripped = text.strip()
    if not stripped:
        return []
    return [RoleBlock(kind="speak_context", content=stripped, raw_tag="plain")]


def _normalize_tag(tag: str) -> RoleBlockKind:
    key = re.sub(r"\s+", " ", tag.strip().lower())
    if key in ("think",):
        return "think"
    if key in ("speak action", "speak_action"):
        return "speak_action"
    if key in ("speak context", "speak_context"):
        return "speak_context"
    if key in ("body action", "body_action"):
        return "body_action"
    if key in ("ask help", "ask_help"):
        return "ask_help"
    return "unknown"


def _scan_any(text: str) -> list[RoleBlock]:
    blocks: list[RoleBlock] = []
    for match in _ANY_BLOCK_RE.finditer(text):
        if match.group(1) is not None:
            content = (match.group(1) or "").strip()
            if content:
                blocks.append(RoleBlock(kind="think", content=content, raw_tag="think"))
            continue
        if match.group(2) is not None:
            tag = match.group(2)
            content = (match.group(3) or "").strip()
            blocks.append(RoleBlock(kind=_normalize_tag(tag), content=content, raw_tag=tag))
            continue
        if match.group(4) is not None:
            tag = match.group(4)
            content = (match.group(5) or "").strip()
            blocks.append(RoleBlock(kind=_normalize_tag(tag), content=content, raw_tag=tag))
            continue
        if match.group(6) is not None:
            tag = match.group(6)
            content = (match.group(7) or "").strip()
            blocks.append(RoleBlock(kind=_normalize_tag(tag), content=content, raw_tag=tag))
    return blocks
