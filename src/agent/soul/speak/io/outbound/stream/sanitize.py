from __future__ import annotations

import re

from .events import SpeakStreamEvent
from .protocol.tags import SPEAK_TAG_NAMES

_TAG_ALT = "|".join(SPEAK_TAG_NAMES)
_CLOSE_TAG_RE = re.compile(rf"\[/(?:{_TAG_ALT})\]", re.IGNORECASE)
_HTML_CLOSE_TAG_RE = re.compile(rf"</(?:{_TAG_ALT}|redacted_thinking)>", re.IGNORECASE)
_HTML_OPEN_TAG_RE = re.compile(rf"<(?:{_TAG_ALT})>", re.IGNORECASE)
_OPEN_TAG_ONLY_RE = re.compile(rf"^\[(?:{_TAG_ALT})\]\s*$", re.IGNORECASE)
# 仅剥掉未闭合的 [/tag 残片；单独的 [ 由 split_hold_tag_suffix 缓冲，不在此剔除
_TRAILING_TAG_FRAGMENT_RE = re.compile(r"\[/[^\]]*$", re.IGNORECASE)

_TEXT_KINDS = frozenset({
    "speak",
    "action",
    "segment",
    "thought",
    "finish",
    "chunk",
})


def sanitize_push_text(text: str) -> str:
    """移除推送文本中的闭合标签与孤立开标签残留。"""
    if not text:
        return ""
    cleaned = _HTML_CLOSE_TAG_RE.sub("", text)
    cleaned = _HTML_OPEN_TAG_RE.sub("", cleaned)
    cleaned = _CLOSE_TAG_RE.sub("", cleaned)
    cleaned = _TRAILING_TAG_FRAGMENT_RE.sub("", cleaned)
    cleaned = re.sub(r"</think>", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    if not cleaned:
        return ""
    if _OPEN_TAG_ONLY_RE.match(cleaned):
        return ""
    return cleaned


def normalize_session_state_text(value: str) -> str:
    cleaned = sanitize_push_text(value.strip()).lower()
    if cleaned in ("append", "share", "recall"):
        return cleaned
    return "finish"


def sanitize_stream_event(event: SpeakStreamEvent) -> SpeakStreamEvent:
    if event.kind == "state":
        raw = event.text or str((event.meta or {}).get("session_state") or "")
        state = normalize_session_state_text(raw)
        if state == event.text and (event.meta or {}).get("session_state") == state:
            return event
        meta = dict(event.meta or {})
        meta["session_state"] = state
        meta.setdefault("tag", "state")
        return SpeakStreamEvent(
            kind="state",
            text=state,
            final=event.final,
            meta=meta,
        )
    if event.kind not in _TEXT_KINDS or not event.text:
        return event
    cleaned = sanitize_push_text(event.text)
    if cleaned == event.text:
        return event
    return SpeakStreamEvent(
        kind=event.kind,
        text=cleaned,
        final=event.final,
        meta=dict(event.meta),
    )


def split_hold_tag_suffix(text: str) -> tuple[str, str]:
    """流式分片时保留末尾未闭合的 `[` / `[/action` / `</speak` 片段。"""
    from .parse.tags import find_next_tag_opener

    idx = text.rfind("<")
    if idx >= 0:
        tail = text[idx:]
        if re.match(r"</[^>]*$", tail):
            return text[:idx], tail
        if re.match(r"<[^>]*$", tail):
            return text[:idx], tail

    idx = text.rfind("[")
    if idx < 0:
        return text, ""
    tail = text[idx:]
    if _CLOSE_TAG_RE.match(tail):
        return text, ""
    if find_next_tag_opener(tail) is not None:
        return text[:idx], tail
    if re.match(rf"\[/?(?:{_TAG_ALT})?$", tail, re.IGNORECASE):
        return text[:idx], tail
    if re.match(r"\[/[^\]]*$", tail):
        return text[:idx], tail
    return text, ""


def split_before_close_tag(text: str) -> tuple[str, str]:
    """将缓冲区拆为（闭合标签前的正文, 闭合标签之后的余下部分）。"""
    best_start: int | None = None
    best_end: int | None = None
    for pattern in (
        _CLOSE_TAG_RE,
        _HTML_CLOSE_TAG_RE,
        re.compile(r"</think>", re.IGNORECASE),
    ):
        match = pattern.search(text)
        if match is None:
            continue
        if best_start is None or match.start() < best_start:
            best_start = match.start()
            best_end = match.end()
    if best_start is None or best_end is None:
        return text, ""
    return text[:best_start], text[best_end:]
