from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

from ..compose.reply_style import SpeakReplyStyle
from ..llm.engine import SpeakLLMEngine
from ..parse.parser import parse_agent_output
from ..parse.tags import SpeakTagBlock
from .events import SpeakStreamEvent
from .segmenter import split_sentences

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
class SpeakStreamPipeline:
    """Speak 流式 flush 推送。"""

    flush_mode: SpeakFlushMode = "segment"
    token_batch_size: int = 4
    min_segment_chars: int = 8
    reply_style: SpeakReplyStyle = field(default_factory=SpeakReplyStyle)
    stream_port: object | None = None

    def _emit(self, session_id: str, event: SpeakStreamEvent) -> None:
        port = self.stream_port
        if port is not None:
            port.emit(session_id, event)

    def stream_generate(
        self,
        engine: SpeakLLMEngine,
        session_id: str,
        user_text: str,
        *,
        system: str = "",
        context: str = "",
    ) -> Iterator[SpeakStreamEvent]:
        token_buf: list[str] = []
        full_parts: list[str] = []

        for token in engine.stream(user_text, system=system, context=context):
            full_parts.append(token)
            token_buf.append(token)
            if self.flush_mode == "token_batch" and len(token_buf) >= self.token_batch_size:
                chunk = "".join(token_buf)
                token_buf.clear()
                event = SpeakStreamEvent(kind="chunk", text=chunk)
                self._emit(session_id, event)
                yield event

        if token_buf:
            chunk = "".join(token_buf)
            event = SpeakStreamEvent(kind="chunk", text=chunk)
            self._emit(session_id, event)
            yield event

        full_text = "".join(full_parts).strip()
        yield from self.emit_parsed_output(session_id, full_text)

    def _emit_tag_block(
        self,
        session_id: str,
        block: SpeakTagBlock,
    ) -> Iterator[SpeakStreamEvent]:
        kind = _STREAM_KIND_BY_TAG.get(block.kind)
        if kind is None:
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

    def emit_parsed_output(
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
        for block in parsed.blocks:
            yield from self._emit_tag_block(session_id, block)

        final = parsed.session_state != "append"
        finish = SpeakStreamEvent(
            kind="finish",
            text=parsed.speak,
            final=final,
            meta=parsed.to_dict(),
        )
        self._emit(session_id, finish)
        yield finish
