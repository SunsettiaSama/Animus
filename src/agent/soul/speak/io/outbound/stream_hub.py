from __future__ import annotations

from collections.abc import Callable

from ...llm.engine import SpeakLLMEngine
from .stream import (
    SpeakAgentOutput,
    SpeakStreamChannel,
    SpeakStreamEvent,
    SpeakStreamPipeline,
    parse_agent_output,
)
from .stream.flush import SpeakFlushMode


class SpeakOutboundStreamHub:
    """Speak 出站：``SpeakService._generate_turn`` → LLM → ``SpeakStreamPipeline`` → WebUI 流。"""

    def __init__(
        self,
        *,
        flush_mode: SpeakFlushMode = "segment",
        emit_fn: Callable[[SpeakStreamEvent], None] | None = None,
        pipeline: SpeakStreamPipeline | None = None,
        channel: SpeakStreamChannel | None = None,
    ) -> None:
        self.channel = channel or SpeakStreamChannel()
        self.pipeline = pipeline or SpeakStreamPipeline(
            flush_mode=flush_mode,
            emit_fn=emit_fn or self.channel.emit,
        )

    def bind_port(self, port) -> None:
        self.channel.bind(port)

    def begin_session(self, session_id: str) -> None:
        self.channel.begin_session(session_id)

    def generate_turn(
        self,
        llm: SpeakLLMEngine,
        session_id: str,
        user_text: str,
        *,
        system: str,
        stream: bool,
    ) -> tuple[str, list[SpeakStreamEvent]]:
        self.begin_session(session_id)
        if stream:
            events = list(
                self.pipeline.stream_generate(
                    llm,
                    session_id,
                    user_text,
                    system=system,
                    context="",
                )
            )
            answer = next(
                (event.text for event in reversed(events) if event.kind == "finish"),
                "",
            )
            return answer, events

        llm_result = llm.generate(user_text, system=system)
        answer = llm_result.text
        events = list(self.pipeline.emit_parsed_output(session_id, answer))
        return answer, events

    @staticmethod
    def parse_output(raw: str) -> SpeakAgentOutput:
        return parse_agent_output(raw)
