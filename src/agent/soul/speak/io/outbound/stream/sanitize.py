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
    "observe",
    "outline",
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


from agent.soul.speak.io.outbound.render_protocol import (
    META_FIELD,
    META_RENDER_TIME_MS,
    META_SESSION_STATE,
    META_WAIT_MS,
    SpeakRenderField,
    field_for_stream_kind,
    render_meta,
)
from agent.soul.speak.io.outbound.render_time import estimate_render_time_ms

_PACE_FIELDS = frozenset({"speak", "body", "observe", "outline"})
_INCOMPLETE_PHASES = frozenset({"delta", "start"})


def _as_render_field(value: str) -> SpeakRenderField:
    table: dict[str, SpeakRenderField] = {
        "thought": "thought",
        "speak": "speak",
        "body": "body",
        "wait": "wait",
        "silence": "silence",
        "typing": "typing",
        "finish": "finish",
        "observe": "observe",
        "outline": "outline",
    }
    if value not in table:
        raise ValueError(f"invalid speak render field: {value!r}")
    return table[value]


def sanitize_stream_event(event: SpeakStreamEvent) -> SpeakStreamEvent:
    meta_in = dict(event.meta or {})
    field = field_for_stream_kind(event.kind, meta_in)

    if event.kind == "state":
        # wait/silence 是渲染字段，不是 session_state
        if field in {"wait", "silence"} or str(meta_in.get("role_op") or "") in {
            "wait",
            "silence",
        }:
            resolved = _as_render_field(
                "silence"
                if field == "silence" or str(meta_in.get("role_op") or "") == "silence"
                else "wait"
            )
            if meta_in.get(META_FIELD) != resolved:
                return SpeakStreamEvent(
                    kind="state",
                    text=event.text or resolved,
                    final=event.final,
                    meta=render_meta(
                        resolved,
                        wait_ms=_as_optional_int(meta_in.get("wait_ms")),
                        seconds=_as_optional_float(meta_in.get("seconds")),
                        extra=meta_in,
                    ),
                )
            return event
        raw = event.text or str(meta_in.get(META_SESSION_STATE) or "")
        state = normalize_session_state_text(raw)
        if state == event.text and meta_in.get(META_SESSION_STATE) == state:
            return event
        meta = dict(meta_in)
        meta[META_SESSION_STATE] = state
        meta.setdefault("tag", "state")
        return SpeakStreamEvent(
            kind="state",
            text=state,
            final=event.final,
            meta=meta,
        )

    ensured_meta = meta_in
    if field is not None and meta_in.get(META_FIELD) != field:
        ensured_meta = render_meta(
            _as_render_field(field),
            phase=str(meta_in.get("phase") or ""),
            wait_ms=_as_optional_int(meta_in.get("wait_ms")),
            seconds=_as_optional_float(meta_in.get("seconds")),
            extra=meta_in,
        )

    if event.kind not in _TEXT_KINDS or not event.text:
        if ensured_meta is meta_in:
            return event
        return SpeakStreamEvent(
            kind=event.kind,
            text=event.text,
            final=event.final,
            meta=ensured_meta,
        )
    cleaned = sanitize_push_text(event.text)
    paced_meta = _stamp_visible_wait(ensured_meta, cleaned, field)
    if cleaned == event.text and paced_meta is meta_in:
        return event
    return SpeakStreamEvent(
        kind=event.kind,
        text=cleaned,
        final=event.final,
        meta=paced_meta,
    )


def _stamp_visible_wait(
    meta: dict,
    text: str,
    field: str | None,
) -> dict:
    if field not in _PACE_FIELDS or not str(text or "").strip():
        return meta
    phase = str(meta.get("phase") or "").strip().lower()
    if phase in _INCOMPLETE_PHASES:
        return meta
    wait_ms = int(meta.get(META_WAIT_MS) or meta.get(META_RENDER_TIME_MS) or 0)
    if wait_ms > 0:
        if meta.get(META_WAIT_MS) == wait_ms and meta.get(META_RENDER_TIME_MS) == wait_ms:
            return meta
        stamped = dict(meta)
        stamped[META_WAIT_MS] = wait_ms
        stamped[META_RENDER_TIME_MS] = wait_ms
        return stamped
    wait_ms = estimate_render_time_ms(text)
    stamped = dict(meta)
    stamped[META_WAIT_MS] = wait_ms
    stamped[META_RENDER_TIME_MS] = wait_ms
    return stamped


def _as_optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _as_optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


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
