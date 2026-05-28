from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from ....llm.engine import SpeakLLMEngine
from .events import SpeakStreamEvent
from .flush import SpeakFlushChannels, SpeakFlushMode
from .parse import parse_agent_output
from .parse.incremental import IncrementalTagStreamParser


@dataclass
class SpeakStreamPipeline:
    """Speak 流式处理器：parse output_format → flush 通道 → 出站抛出。"""

    flush_mode: SpeakFlushMode = "segment"
    token_batch_size: int = 4
    min_segment_chars: int = 8
    emit_fn: Callable[[str, SpeakStreamEvent], None] | None = None

    def _emit(self, session_id: str, event: SpeakStreamEvent) -> None:
        if self.emit_fn is not None:
            self.emit_fn(session_id, event)

    def _flush_channels(self) -> SpeakFlushChannels:
        return SpeakFlushChannels.create(
            flush_mode=self.flush_mode,
            token_batch_size=self.token_batch_size,
            min_segment_chars=self.min_segment_chars,
            emit_fn=self._emit,
        )

    def stream_generate(
        self,
        engine: SpeakLLMEngine,
        session_id: str,
        user_text: str,
        *,
        system: str = "",
        context: str = "",
    ) -> Iterator[SpeakStreamEvent]:
        full_parts: list[str] = []

        if self.flush_mode == "segment":
            incremental = IncrementalTagStreamParser(
                min_segment_chars=self.min_segment_chars,
                emit_fn=self._emit,
            )
            for token in engine.stream(user_text, system=system, context=context):
                full_parts.append(token)
                yield from incremental.push(session_id, token)
            yield from incremental.flush(session_id)
        else:
            channels = self._flush_channels()
            for token in engine.stream(user_text, system=system, context=context):
                full_parts.append(token)
                if channels.token_batch is not None:
                    yield from channels.token_batch.push(session_id, token)
            if channels.token_batch is not None:
                yield from channels.token_batch.drain(session_id)

        full_text = "".join(full_parts).strip()
        yield from self.emit_finish_only(session_id, full_text)

    def emit_finish_only(
        self,
        session_id: str,
        text: str,
    ) -> Iterator[SpeakStreamEvent]:
        normalized = text.strip()
        if not normalized:
            finish = SpeakStreamEvent(kind="finish", text="", final=True)
            self._emit(session_id, finish)
            yield finish
            return

        parsed = parse_agent_output(normalized)
        final = parsed.session_state not in ("append", "share", "recall")
        finish = SpeakStreamEvent(
            kind="finish",
            text=parsed.speak,
            final=final,
            meta=parsed.to_dict(),
        )
        self._emit(session_id, finish)
        yield finish

    def emit_parsed_output(
        self,
        session_id: str,
        text: str,
        *,
        channels: SpeakFlushChannels | None = None,
    ) -> Iterator[SpeakStreamEvent]:
        normalized = text.strip()
        if not normalized:
            finish = SpeakStreamEvent(kind="finish", text="", final=True)
            self._emit(session_id, finish)
            yield finish
            return

        flush = channels or self._flush_channels()
        parsed = parse_agent_output(normalized)
        for block in parsed.blocks:
            yield from flush.tag_dispatch.flush_block(session_id, block)

        final = parsed.session_state not in ("append", "share", "recall")
        finish = SpeakStreamEvent(
            kind="finish",
            text=parsed.speak,
            final=final,
            meta=parsed.to_dict(),
        )
        self._emit(session_id, finish)
        yield finish
