from __future__ import annotations

import re
from dataclasses import dataclass

from ..protocol.tags import SPEAK_TAG_NAMES
from ..sanitize import sanitize_push_text
from .normalize import has_structured_tags, normalize_agent_output

_ACTION_MARKER = "（动作）"

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
_TAG_HTML_OPEN_RE = re.compile(rf"<({_TAG_ALTERNATION})>", re.IGNORECASE)

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
    """返回 text 中最早的 L1(:)、L2(]) 或 HTML(<tag>) 标签头 match。"""
    matches: list[re.Match[str]] = []
    for pattern in (_TAG_L1_OPEN_RE, _TAG_BRACKET_OPEN_RE, _TAG_HTML_OPEN_RE):
        found = pattern.search(text)
        if found is not None:
            matches.append(found)
    if not matches:
        return None
    return min(matches, key=lambda item: item.start())


def opener_tag_kind(match: re.Match[str]) -> str:
    return match.group(1).lower()


def opener_consumed_len(match: re.Match[str]) -> int:
    return match.end()


def opener_is_bracket_layer(match: re.Match[str]) -> bool:
    token = match.group(0)
    return (token.endswith("]") and ":" not in token) or token.startswith("<")


def iter_tag_blocks_l1(normalized: str) -> list[SpeakTagBlock]:
    blocks: list[SpeakTagBlock] = []
    last_end = 0
    for match in _TAG_L1_RE.finditer(normalized):
        between = normalized[last_end : match.start()].strip()
        if between:
            blocks.append(SpeakTagBlock("speak", between))
        content = _normalize_block_content(
            match.group(1).lower(),
            match.group(2),
        )
        blocks.append(SpeakTagBlock(match.group(1).lower(), content))
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
        kind = match.group(1).lower()
        content = _normalize_block_content(kind, match.group(2))
        blocks.append(SpeakTagBlock(kind, content))
        last_end = match.end()

    tail = normalized[last_end:].strip()
    if tail:
        blocks.append(SpeakTagBlock("speak", tail))
    return blocks


def _close_tag_end(text: str, start: int, kind: str) -> int | None:
    names = [kind]
    if kind == "think":
        names.extend(["redacted_thinking"])
    best: int | None = None
    for name in names:
        for pattern in (rf"\[/{re.escape(name)}\]", rf"</{re.escape(name)}>"):
            close_match = re.search(pattern, text[start:], re.IGNORECASE)
            if close_match is None:
                continue
            pos = start + close_match.start()
            if best is None or pos < best:
                best = pos
    return best


def _normalize_block_content(kind: str, content: str) -> str:
    return sanitize_push_text(content).strip()


def iter_tag_blocks_unified(normalized: str) -> list[SpeakTagBlock]:
    """成对 [tag]…[/tag] 与 legacy [tag:…] 混排解析。"""
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
            close_at = _close_tag_end(normalized, content_start, kind)
            next_head = _TAG_ANY_HEAD_RE.search(normalized, content_start)
            if close_at is not None and (next_head is None or close_at <= next_head.start()):
                content = normalized[content_start:close_at].strip()
                close_match = re.search(
                    rf"(?:\[/{re.escape(kind)}\]|</{re.escape(kind)}>)",
                    normalized[content_start:],
                    re.IGNORECASE,
                )
                last_end = content_start + close_match.end() if close_match else content_start
            else:
                content_end = next_head.start() if next_head else len(normalized)
                content = normalized[content_start:content_end].strip()
                last_end = content_end

        content = _normalize_block_content(kind, content)
        if content or kind in ("state", "think", "recall", "anchor", "observe"):
            blocks.append(SpeakTagBlock(kind, content))

    tail = sanitize_push_text(normalized[last_end:]).strip()
    if tail:
        blocks.append(SpeakTagBlock("speak", tail))
    return blocks


def iter_blocks_from_action_markers(text: str) -> list[SpeakTagBlock]:
    """纯文本中的（动作）前缀段落 → action / speak 块。"""
    if _ACTION_MARKER not in text:
        return []
    blocks: list[SpeakTagBlock] = []
    parts = text.split(_ACTION_MARKER)
    head = parts[0].strip()
    if head:
        blocks.append(SpeakTagBlock("speak", sanitize_push_text(head)))
    for segment in parts[1:]:
        segment = segment.strip()
        if not segment:
            continue
        lines = segment.split("\n")
        action_line = lines[0].strip()
        speak_body = "\n".join(lines[1:]).strip()
        if action_line:
            blocks.append(SpeakTagBlock("action", sanitize_push_text(action_line)))
        if speak_body:
            blocks.append(SpeakTagBlock("speak", sanitize_push_text(speak_body)))
    return blocks


def iter_tag_blocks(raw: str) -> list[SpeakTagBlock]:
    """按出现顺序解析 speak 标签块。

    主协议：成对 [tag]content[/tag]
    兼容：legacy [tag:content]；可与成对标签混排，走 unified
    标签间裸文本视为 speak。
    """
    normalized = normalize_agent_output(raw.strip())
    if not normalized:
        return []

    if has_structured_tags(raw):
        if has_l2_tags(normalized) or _TAG_HTML_OPEN_RE.search(raw):
            blocks = iter_tag_blocks_unified(normalized)
            if blocks:
                return blocks
        if has_l1_tags(normalized):
            blocks = iter_tag_blocks_l1(normalized)
            if blocks:
                return blocks

    marker_blocks = iter_blocks_from_action_markers(normalized)
    if marker_blocks:
        return marker_blocks

    return [SpeakTagBlock("speak", normalized)]
