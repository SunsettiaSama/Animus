from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from .....tools.anchor import ANCHOR_ENABLED
from ..events import SpeakStreamEvent
from ..protocol.tags import FRONTEND_SUPPRESSED_TAGS, SPEAK_TAG_NAMES
from ..sanitize import (
    sanitize_push_text,
    sanitize_stream_event,
    split_before_close_tag,
    split_hold_tag_suffix,
)
from .tags import (
    _TAG_ALTERNATION,
    _TAG_L1_OPEN_RE,
    find_next_tag_opener,
    opener_consumed_len,
    opener_is_bracket_layer,
    opener_tag_kind,
)

_TAG_NAMES_PATTERN = _TAG_ALTERNATION
_TAG_OPEN_RE = _TAG_L1_OPEN_RE

_STREAM_KIND_BY_TAG = {
    "think": "thought",
    "speak": "speak",
    "action": "action",
    "state": "state",
    "anchor": "anchor",
    "observe": "observe",
}

_STREAMABLE_TAGS = frozenset({"speak", "action"})


@dataclass
class _ActiveTag:
    kind: str
    content: str = ""
    speak_emitted: int = 0
    streamed: bool = False
    bracket_layer: bool = False
    hold_suffix: str = ""


@dataclass
class IncrementalTagStreamParser:
    """LLM token 增量解析：识别 tag 开闭，边生成边抛出流式事件。"""

    min_segment_chars: int = 8
    emit_fn: Callable[[str, SpeakStreamEvent], None] | None = None
    _pending: str = ""
    _active: _ActiveTag | None = None
    _saw_tag: bool = False
    _plain_speak_open: bool = False

    def _emit(self, session_id: str, event: SpeakStreamEvent) -> SpeakStreamEvent:
        event = sanitize_stream_event(event)
        if self.emit_fn is not None:
            self.emit_fn(session_id, event)
        return event

    def push(self, session_id: str, token: str) -> Iterator[SpeakStreamEvent]:
        if self._active is not None:
            yield from self._push_in_tag(session_id, token)
            return
        self._pending += token
        yield from self._drain_outside(session_id)

    def flush(self, session_id: str) -> Iterator[SpeakStreamEvent]:
        if self._active is not None:
            remainder = self._active.hold_suffix + self._pending
            self._pending = ""
            self._active.hold_suffix = ""
            if remainder:
                self._active.content += remainder
                yield from self._emit_tag_piece(session_id, self._active, remainder, closing=False)
            yield from self._close_active_tag(session_id, self._active)
            self._active = None
            return

        if self._pending:
            yield from self._emit_plain_speak_delta(session_id, self._pending)
            self._pending = ""
        if self._plain_speak_open:
            yield self._emit(
                session_id,
                SpeakStreamEvent(kind="speak", text="", meta={"phase": "end", "tag": "speak"}),
            )
            self._plain_speak_open = False
        self._pending = ""

    def _open_tag(self, session_id: str, match: re.Match[str]) -> Iterator[SpeakStreamEvent]:
        tag_kind = opener_tag_kind(match)
        remainder = self._pending[opener_consumed_len(match) :]
        self._pending = ""
        self._active = _ActiveTag(
            kind=tag_kind,
            bracket_layer=opener_is_bracket_layer(match),
        )
        self._saw_tag = True
        if tag_kind not in FRONTEND_SUPPRESSED_TAGS:
            yield self._emit(
                session_id,
                SpeakStreamEvent(kind="tag", text="", meta={"tag": tag_kind}),
            )
        if remainder:
            yield from self._push_in_tag(session_id, remainder)

    def _drain_outside(self, session_id: str) -> Iterator[SpeakStreamEvent]:
        while self._pending:
            match = find_next_tag_opener(self._pending)
            if match is not None and match.start() == 0:
                yield from self._open_tag(session_id, match)
                continue

            if match is not None:
                before = self._pending[: match.start()]
                if before:
                    yield from self._emit_plain_speak_delta(session_id, before)
                if self._plain_speak_open:
                    yield self._emit(
                        session_id,
                        SpeakStreamEvent(kind="speak", text="", meta={"phase": "end", "tag": "speak"}),
                    )
                    self._plain_speak_open = False
                self._pending = self._pending[match.start() :]
                yield from self._open_tag(session_id, match)
                continue

            hold = self._hold_incomplete_opener(self._pending)
            if hold:
                processable, self._pending = self._pending[:-hold], self._pending[-hold:]
            else:
                processable, self._pending = self._pending, ""

            if not processable:
                break

            if find_next_tag_opener(processable) is not None:
                self._pending = processable + self._pending
                continue

            yield from self._emit_plain_speak_delta(session_id, processable)
            break

    def _push_in_tag(self, session_id: str, token: str) -> Iterator[SpeakStreamEvent]:
        assert self._active is not None
        if self._active.bracket_layer:
            yield from self._push_in_tag_l2(session_id, token)
            return
        yield from self._push_in_tag_l1(session_id, token)

    def _split_l1_close(self, buf: str, tag_kind: str) -> tuple[str, str] | None:
        """L1 闭合：优先 [/tag]，避免 [state:finish[/state] 在首个 ] 处截断。"""
        bracket = f"[/{tag_kind.lower()}]"
        bracket_idx = buf.lower().find(bracket)
        simple_idx = buf.find("]")
        if bracket_idx >= 0 and (simple_idx < 0 or bracket_idx <= simple_idx):
            return buf[:bracket_idx], buf[bracket_idx + len(bracket) :]
        if simple_idx >= 0:
            return buf[:simple_idx], buf[simple_idx + 1 :]
        return None

    def _push_in_tag_l1(self, session_id: str, token: str) -> Iterator[SpeakStreamEvent]:
        assert self._active is not None
        buf = token
        while buf:
            active = self._active
            assert active is not None
            split = self._split_l1_close(buf, active.kind)
            if split is None:
                active.content += buf
                yield from self._emit_tag_piece(session_id, active, buf, closing=False)
                return

            piece, buf = split
            if piece:
                active.content += piece
                yield from self._emit_tag_piece(session_id, active, piece, closing=False)
            yield from self._close_active_tag(session_id, active)
            self._active = None
            if buf:
                self._pending = buf
                buf = ""
                yield from self._drain_outside(session_id)

    def _push_in_tag_l2(self, session_id: str, token: str) -> Iterator[SpeakStreamEvent]:
        assert self._active is not None
        self._pending += token
        while self._pending:
            active = self._active
            assert active is not None
            before_close, after_close = split_before_close_tag(self._pending)
            if after_close or (before_close != self._pending):
                if before_close:
                    active.content += before_close
                    yield from self._emit_tag_piece(session_id, active, before_close, closing=False)
                self._pending = after_close
                yield from self._close_active_tag(session_id, active)
                self._active = None
                if self._pending:
                    yield from self._drain_outside(session_id)
                return

            next_match = find_next_tag_opener(self._pending)
            if next_match is None:
                processable, hold = split_hold_tag_suffix(self._pending)
                if not hold:
                    opener_hold = self._hold_incomplete_opener(self._pending)
                    if opener_hold:
                        processable, hold = (
                            self._pending[:-opener_hold],
                            self._pending[-opener_hold:],
                        )
                    else:
                        processable, hold = self._pending, ""
                self._pending = hold
                if processable:
                    active.content += processable
                    yield from self._emit_tag_piece(
                        session_id,
                        active,
                        processable,
                        closing=False,
                    )
                return

            if next_match.start() > 0:
                piece = self._pending[: next_match.start()]
                self._pending = self._pending[next_match.start() :]
                active.content += piece
                yield from self._emit_tag_piece(session_id, active, piece, closing=False)
                continue

            yield from self._close_active_tag(session_id, active)
            self._active = None
            yield from self._drain_outside(session_id)
            return

    def _close_active_tag(self, session_id: str, active: _ActiveTag) -> Iterator[SpeakStreamEvent]:
        stream_kind = _STREAM_KIND_BY_TAG.get(active.kind)
        if stream_kind is None:
            return
        if active.kind == "anchor" and not ANCHOR_ENABLED:
            return
        if active.kind in FRONTEND_SUPPRESSED_TAGS:
            return

        content = active.content.strip()
        if active.kind == "speak":
            remainder = active.content[active.speak_emitted :].strip()
            if remainder:
                if active.streamed:
                    yield self._emit(
                        session_id,
                        SpeakStreamEvent(kind="speak", text="", meta={"phase": "end", "tag": "speak"}),
                    )
                else:
                    yield self._emit(
                        session_id,
                        SpeakStreamEvent(
                            kind="speak",
                            text=remainder,
                            meta={"phase": "end", "tag": "speak"},
                        ),
                    )
            return

        if active.kind == "action":
            if active.streamed:
                yield self._emit(
                    session_id,
                    SpeakStreamEvent(kind="action", text="", meta={"phase": "end", "tag": "action"}),
                )
            elif content:
                yield self._emit(
                    session_id,
                    SpeakStreamEvent(
                        kind="action",
                        text=content,
                        meta={"phase": "end", "tag": "action"},
                    ),
                )
            return

        if not content:
            return

        if active.kind == "state":
            yield self._emit(
                session_id,
                SpeakStreamEvent(
                    kind="state",
                    text=content,
                    meta={"session_state": content, "tag": "state"},
                ),
            )
            return

        yield self._emit(
            session_id,
            SpeakStreamEvent(kind=stream_kind, text=content, meta={"tag": active.kind}),
        )

    def _emit_tag_piece(
        self,
        session_id: str,
        active: _ActiveTag,
        piece: str,
        *,
        closing: bool,
    ) -> Iterator[SpeakStreamEvent]:
        piece = active.hold_suffix + piece
        active.hold_suffix = ""
        emit_part, hold = split_hold_tag_suffix(piece)
        active.hold_suffix = hold
        piece = sanitize_push_text(emit_part)
        if not piece:
            return
        if active.kind == "speak":
            active.streamed = True
            yield self._emit(
                session_id,
                SpeakStreamEvent(
                    kind="speak",
                    text=piece,
                    meta={"phase": "delta", "tag": "speak"},
                ),
            )
            return
        if active.kind == "action":
            active.streamed = True
            yield self._emit(
                session_id,
                SpeakStreamEvent(
                    kind="action",
                    text=piece,
                    meta={"phase": "delta", "tag": "action"},
                ),
            )

    def _emit_plain_speak(self, session_id: str, text: str) -> Iterator[SpeakStreamEvent]:
        if not text:
            return
        yield self._emit(
            session_id,
            SpeakStreamEvent(kind="tag", text="", meta={"tag": "speak"}),
        )
        yield self._emit(
            session_id,
            SpeakStreamEvent(
                kind="speak",
                text=text,
                meta={"phase": "end", "tag": "speak"},
            ),
        )

    def _emit_plain_speak_delta(self, session_id: str, piece: str) -> Iterator[SpeakStreamEvent]:
        if not piece:
            return
        if not self._plain_speak_open:
            yield self._emit(
                session_id,
                SpeakStreamEvent(kind="tag", text="", meta={"tag": "speak"}),
            )
            self._plain_speak_open = True
        yield self._emit(
            session_id,
            SpeakStreamEvent(
                kind="speak",
                text=piece,
                meta={"phase": "delta", "tag": "speak"},
            ),
        )

    @staticmethod
    def _hold_incomplete_opener(text: str) -> int:
        idx = text.rfind("[")
        if idx < 0:
            return 0
        tail = text[idx:]
        if find_next_tag_opener(tail) is not None:
            return 0
        if _TAG_L1_OPEN_RE.match(tail):
            return len(tail)
        if re.match(r"\[[a-z]*$", tail, re.IGNORECASE):
            return len(tail)
        if re.match(rf"\[({_TAG_NAMES_PATTERN}):[^\]]*$", tail, re.IGNORECASE):
            return len(tail)
        if re.match(rf"\[({_TAG_NAMES_PATTERN})?$", tail, re.IGNORECASE):
            return len(tail)
        if re.match(rf"\[({_TAG_NAMES_PATTERN})\]?$", tail, re.IGNORECASE):
            return len(tail)
        return 0
