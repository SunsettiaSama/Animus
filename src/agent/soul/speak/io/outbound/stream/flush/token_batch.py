from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from ..events import SpeakStreamEvent
from ..sanitize import sanitize_push_text


@dataclass
class SpeakTokenBatchChannel:
    """LLM token 批量 flush 通道。"""

    batch_size: int = 4
    emit_fn: Callable[[str, SpeakStreamEvent], None] | None = None
    _buffer: list[str] = field(default_factory=list)

    def _emit(self, session_id: str, event: SpeakStreamEvent) -> None:
        if self.emit_fn is not None:
            self.emit_fn(session_id, event)

    def push(self, session_id: str, token: str) -> Iterator[SpeakStreamEvent]:
        self._buffer.append(token)
        if len(self._buffer) < self.batch_size:
            return
        chunk = sanitize_push_text("".join(self._buffer))
        self._buffer.clear()
        if not chunk:
            return
        event = SpeakStreamEvent(kind="chunk", text=chunk)
        self._emit(session_id, event)
        yield event

    def drain(self, session_id: str) -> Iterator[SpeakStreamEvent]:
        if not self._buffer:
            return
        chunk = sanitize_push_text("".join(self._buffer))
        self._buffer.clear()
        if not chunk:
            return
        event = SpeakStreamEvent(kind="chunk", text=chunk)
        self._emit(session_id, event)
        yield event

    def reset(self) -> None:
        self._buffer.clear()
