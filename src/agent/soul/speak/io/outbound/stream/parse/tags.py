from __future__ import annotations

import re
from dataclasses import dataclass

from ..protocol.tags import SPEAK_TAG_NAMES

_TAG_ALTERNATION = "|".join(SPEAK_TAG_NAMES)
_TAG_NEXT_HEAD = rf"\[(?:{_TAG_ALTERNATION})(?::|])"

# L1: 标准协议 [tag:content]
_TAG_L1_RE = re.compile(rf"\[({_TAG_ALTERNATION}):([^\]]*)\]", re.IGNORECASE)
_TAG_L1_OPEN_RE = re.compile(rf"\[({_TAG_ALTERNATION}):", re.IGNORECASE)

# L2: 兜底 [tag]content（无冒号）
_TAG_L2_BLOCK_RE = re.compile(
    rf"\[({_TAG_ALTERNATION})\](.*?)(?={_TAG_NEXT_HEAD}|\Z)",
    re.IGNORECASE | re.DOTALL,
)
_TAG_BRACKET_OPEN_RE = re.compile(rf"\[({_TAG_ALTERNATION})\](?!:)", re.IGNORECASE)

# 增量解析：仅匹配标签头
_TAG_ANY_HEAD_RE = re.compile(
    rf"\[({_TAG_ALTERNATION})(?::|])",
    re.IGNORECASE,
)

_TAG_OPEN_RE = _TAG_L1_OPEN_RE


@dataclass(frozen=True)
class SpeakTagBlock:
    kind: str
    content: str


def has_l1_tags(raw: str) -> bool:
    return _TAG_L1_RE.search(raw) is not None


def has_l2_tags(raw: str) -> bool:
    return _TAG_BRACKET_OPEN_RE.search(raw) is not None


def find_next_tag_opener(text: str) -> re.Match[str] | None:
    """返回 text 中最早的 L1(:) 或 L2(]) 标签头 match。"""
    l1 = _TAG_L1_OPEN_RE.search(text)
    l2 = _TAG_BRACKET_OPEN_RE.search(text)
    if l1 is None:
        return l2
    if l2 is None:
        return l1
    return l1 if l1.start() <= l2.start() else l2


def opener_tag_kind(match: re.Match[str]) -> str:
    return match.group(1).lower()


def opener_consumed_len(match: re.Match[str]) -> int:
    return match.end()


def opener_is_bracket_layer(match: re.Match[str]) -> bool:
    return match.group(0).endswith("]")


def iter_tag_blocks_l1(normalized: str) -> list[SpeakTagBlock]:
    blocks: list[SpeakTagBlock] = []
    last_end = 0
    for match in _TAG_L1_RE.finditer(normalized):
        between = normalized[last_end : match.start()].strip()
        if between:
            blocks.append(SpeakTagBlock("speak", between))
        blocks.append(SpeakTagBlock(match.group(1).lower(), match.group(2).strip()))
        last_end = match.end()

    tail = normalized[last_end:].strip()
    if tail:
        blocks.append(SpeakTagBlock("speak", tail))
    return blocks


def iter_tag_blocks_l2(normalized: str) -> list[SpeakTagBlock]:
    blocks: list[SpeakTagBlock] = []
    last_end = 0
    for match in _TAG_L2_BLOCK_RE.finditer(normalized):
        between = normalized[last_end : match.start()].strip()
        if between:
            blocks.append(SpeakTagBlock("speak", between))
        blocks.append(SpeakTagBlock(match.group(1).lower(), match.group(2).strip()))
        last_end = match.end()

    tail = normalized[last_end:].strip()
    if tail:
        blocks.append(SpeakTagBlock("speak", tail))
    return blocks


def iter_tag_blocks_unified(normalized: str) -> list[SpeakTagBlock]:
    """L1/L2 混排：colon 内容在 [] 内，bracket 内容在 ] 后直到下一标签头。"""
    blocks: list[SpeakTagBlock] = []
    last_end = 0
    for match in _TAG_ANY_HEAD_RE.finditer(normalized):
        between = normalized[last_end : match.start()].strip()
        if between:
            blocks.append(SpeakTagBlock("speak", between))

        kind = match.group(1).lower()
        head = match.group(0)
        if head.endswith(":"):
            close_idx = normalized.find("]", match.end() - 1)
            if close_idx < 0:
                content = normalized[match.end() :].strip()
                last_end = len(normalized)
            else:
                content = normalized[match.end() : close_idx].strip()
                last_end = close_idx + 1
        else:
            content_start = match.end()
            next_head = _TAG_ANY_HEAD_RE.search(normalized, content_start)
            content_end = next_head.start() if next_head else len(normalized)
            content = normalized[content_start:content_end].strip()
            last_end = content_end

        if content or kind in ("state", "think", "recall", "anchor", "observe"):
            blocks.append(SpeakTagBlock(kind, content))

    tail = normalized[last_end:].strip()
    if tail:
        blocks.append(SpeakTagBlock("speak", tail))
    return blocks


def iter_tag_blocks(raw: str) -> list[SpeakTagBlock]:
    """按出现顺序解析 speak 标签块。

    L1: [tag:content] 标准协议（无 L2 标签时）
    L2: [tag]content 正则兜底；可与 L1 混排，走 unified
    标签间裸文本视为 speak。
    """
    normalized = raw.strip()
    if not normalized:
        return []

    if has_l2_tags(normalized):
        blocks = iter_tag_blocks_unified(normalized)
        if blocks:
            return blocks

    if has_l1_tags(normalized):
        blocks = iter_tag_blocks_l1(normalized)
        if blocks:
            return blocks

    return [SpeakTagBlock("speak", normalized)]
