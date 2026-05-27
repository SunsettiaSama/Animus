from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Literal

from .....tools.anchor import ANCHOR_ENABLED
from ..events import SpeakStreamEvent
from ..parse.tags import SpeakTagBlock
from .segment import split_sentences

SpeakFlushMode = Literal["segment", "token_batch"]

_STREAM_KIND_BY_TAG = {
    "think": "thought",
    "speak": "speak",
    "action": "action",
    "state": "state",
    "anchor": "anchor",
    "observe": "observe",
}


@dataclass
class SpeakTagFlushDispatcher:
    """标签块 flush 通道：将 parse 结果映射为流式事件。"""

    flush_mode: SpeakFlushMode = "segment"
    min_segment_chars: int = 8
    emit_fn: Callable[[str, SpeakStreamEvent], None] | None = None

    def _emit(self, session_id: str, event: SpeakStreamEvent) -> None:
        if self.emit_fn is not None:
            self.emit_fn(session_id, event)

    def flush_block(
        self,
        session_id: str,
        block: SpeakTagBlock,
    ) -> Iterator[SpeakStreamEvent]:
        kind = _STREAM_KIND_BY_TAG.get(block.kind)
        if kind is None:
            return
        if block.kind == "anchor" and not ANCHOR_ENABLED:
            return

        if block.kind == "speak" and self.flush_mode == "segment":
            segments = split_sentences(block.content, min_chars=self.min_segment_chars)
            if not segments:
                segments = [block.content]
            for segment in segments:
                event = SpeakStreamEvent(kind="speak", text=segment)
                self._emit(session_id, event)
                yield event
            return

        if block.kind == "state":
            event = SpeakStreamEvent(
                kind="state",
                text=block.content,
                meta={"session_state": block.content},
            )
            self._emit(session_id, event)
            yield event
            return

        event = SpeakStreamEvent(kind=kind, text=block.content)
        self._emit(session_id, event)
        yield event
