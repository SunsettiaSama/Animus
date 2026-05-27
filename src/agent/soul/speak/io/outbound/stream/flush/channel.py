from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..events import SpeakStreamEvent
from .dispatch import SpeakFlushMode, SpeakTagFlushDispatcher
from .token_batch import SpeakTokenBatchChannel


@dataclass
class SpeakFlushChannels:
    """Speak 流式 flush 通道组：token 批量 + 标签块分发。"""

    tag_dispatch: SpeakTagFlushDispatcher
    token_batch: SpeakTokenBatchChannel | None = None

    @classmethod
    def create(
        cls,
        *,
        flush_mode: SpeakFlushMode,
        token_batch_size: int = 4,
        min_segment_chars: int = 8,
        emit_fn: Callable[[str, SpeakStreamEvent], None] | None = None,
    ) -> SpeakFlushChannels:
        tag_dispatch = SpeakTagFlushDispatcher(
            flush_mode=flush_mode,
            min_segment_chars=min_segment_chars,
            emit_fn=emit_fn,
        )
        token_batch = None
        if flush_mode == "token_batch":
            token_batch = SpeakTokenBatchChannel(
                batch_size=token_batch_size,
                emit_fn=emit_fn,
            )
        return cls(tag_dispatch=tag_dispatch, token_batch=token_batch)
