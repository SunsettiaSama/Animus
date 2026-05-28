from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from .....tools.anchor import ANCHOR_ENABLED
from ..events import SpeakStreamEvent
from ..protocol.tags import FRONTEND_SUPPRESSED_TAGS, SPEAK_TAG_NAMES
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
_SENTENCE_END_RE = re.compile(r"(?<=[。！？；\n])|(?<=[.!?;]\s)")

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
            remainder = self._pending
            self._pending = ""
            if remainder:
                self._active.content += remainder
                yield from self._emit_tag_piece(session_id, self._active, remainder, closing=False)
            yield from self._close_active_tag(session_id, self._active)
            self._active = None
            return

        if self._pending.strip():
            if self._saw_tag:
                yield from self._emit_plain_speak(session_id, self._pending.strip())
            else:
                yield from self._emit_plain_speak_delta(session_id, self._pending)
                yield self._emit(
                    session_id,
                    SpeakStreamEvent(kind="speak", text="", meta={"phase": "end", "tag": "speak"}),
                )
                self._plain_speak_open = False
        elif self._plain_speak_open:
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
                if before.strip():
                    yield from self._emit_plain_speak(session_id, before.strip())
                elif self._plain_speak_open:
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

            if not self._saw_tag:
                yield from self._emit_plain_speak_delta(session_id, processable)
            elif processable.strip():
                yield from self._emit_plain_speak(session_id, processable.strip())
            break

    def _push_in_tag(self, session_id: str, token: str) -> Iterator[SpeakStreamEvent]:
        assert self._active is not None
        if self._active.bracket_layer:
            yield from self._push_in_tag_l2(session_id, token)
            return
        yield from self._push_in_tag_l1(session_id, token)

    def _push_in_tag_l1(self, session_id: str, token: str) -> Iterator[SpeakStreamEvent]:
        assert self._active is not None
        buf = token
        while buf:
            active = self._active
            assert active is not None
            close_idx = buf.find("]")
            if close_idx < 0:
                active.content += buf
                yield from self._emit_tag_piece(session_id, active, buf, closing=False)
                return

            piece = buf[:close_idx]
            buf = buf[close_idx + 1 :]
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
            next_match = find_next_tag_opener(self._pending)
            if next_match is None:
                hold = self._hold_incomplete_opener(self._pending)
                if hold:
                    processable, self._pending = self._pending[:-hold], self._pending[-hold:]
                else:
                    processable, self._pending = self._pending, ""
                if processable:
                    active.content += processable
                    yield from self._emit_tag_piece(session_id, active, processable, closing=False)
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
            yield from self._emit_completed_speak_sentences(session_id, active)
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

    def _emit_completed_speak_sentences(
        self,
        session_id: str,
        active: _ActiveTag,
    ) -> Iterator[SpeakStreamEvent]:
        tail = active.content[active.speak_emitted :]
        if not tail.strip():
            return

        parts = [segment.strip() for segment in _SENTENCE_END_RE.split(tail) if segment.strip()]
        if not parts:
            return

        ends_with_break = bool(re.search(r"[。！？；\n]$|[.!?;]$", active.content.rstrip()))
        complete = parts if ends_with_break else parts[:-1]
        if not complete:
            return

        offset = active.speak_emitted
        for segment in complete:
            start = active.content.find(segment, offset)
            if start < 0:
                continue
            end = start + len(segment)
            offset = end
            while offset < len(active.content) and active.content[offset].isspace():
                offset += 1
            active.speak_emitted = offset

        yield self._emit(
            session_id,
            SpeakStreamEvent(kind="speak", text="", meta={"phase": "end", "tag": "speak"}),
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
