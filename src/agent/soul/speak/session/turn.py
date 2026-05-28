from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..compose.bundle import SpeakPromptBundle, SpeakTurnMode
from ..io.outbound.stream import SpeakAgentOutput, SpeakStreamEvent, SpeakStreamPipeline
from ..io.outbound.stream.channel import SpeakStreamChannel
from ..llm.engine import SpeakLLMEngine
from .chunk import SpeakSubjectiveChunk, SpeakTurnChunk
from .queue.types import InterruptContext
from .service import SpeakSessionService

if TYPE_CHECKING:
    from ..service import SpeakTurnResult

_APPEND_CONTINUE_INSTRUCTION = (
    "请继续完成本轮尚未说完的内容；输出仍需包含 think 与 state:finish（或 append）。"
)


@dataclass
class SessionTurnHost:
    compose_bundle: Callable[..., SpeakPromptBundle]
    llm: SpeakLLMEngine
    stream_pipeline: SpeakStreamPipeline
    outbound_stream: SpeakStreamChannel
    record_turn: Callable[[SpeakTurnChunk], Any]
    schedule_compose: Callable[[str], None]
    on_memory_activation: Callable[[str, str, str], None] | None = None
    resolve_interactor_id: Callable[[str], str] | None = None
    continue_share_handoff: Callable[..., tuple[str, list[SpeakStreamEvent], "SpeakAgentOutput"] | None] | None = None
    continue_recall_handoff: Callable[..., tuple[str, list[SpeakStreamEvent], "SpeakAgentOutput"] | None] | None = None
    compose_from_queue: Callable[..., SpeakPromptBundle | None] | None = None
    parse_agent_output: Callable[[str], SpeakAgentOutput] | None = None


def _generate_with_outbound(
    host: SessionTurnHost,
    session_id: str,
    user_text: str,
    *,
    system: str,
    stream: bool,
    on_partial: Callable[[str], None] | None = None,
) -> tuple[str, list[SpeakStreamEvent]]:
    host.outbound_stream.begin_session(session_id)
    if stream:
        events = list(
            host.stream_pipeline.stream_generate(
                host.llm,
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
        if on_partial is not None:
            spoken = ""
            for event in events:
                if event.kind == "speak":
                    spoken += event.text
                    on_partial(spoken)
            if answer.strip():
                on_partial(answer.strip())
        return answer, events

    llm_result = host.llm.generate(user_text, system=system)
    answer = llm_result.text
    if on_partial is not None and answer.strip():
        on_partial(answer.strip())
    events = list(host.stream_pipeline.emit_parsed_output(session_id, answer))
    return answer, events


def _resolve_handoff(
    host: SessionTurnHost,
    session_id: str,
    user_text: str,
    *,
    system: str,
    stream: bool,
    parsed: SpeakAgentOutput,
    notes: list[str],
) -> tuple[str, list[SpeakStreamEvent], SpeakAgentOutput] | None:
    if parsed.session_state == "share" and host.continue_share_handoff is not None:
        notes.append("session_state: share")
        return host.continue_share_handoff(
            session_id,
            user_text,
            system=system,
            stream=stream,
            notes=notes,
        )
    if parsed.session_state == "recall" and host.continue_recall_handoff is not None:
        notes.append("session_state: recall")
        return host.continue_recall_handoff(
            session_id,
            user_text,
            system=system,
            stream=stream,
            notes=notes,
            parsed=parsed,
        )
    return None


def run_session_turn(
    manager: SpeakSessionService,
    host: SessionTurnHost,
    session_id: str,
    user_text: str,
    *,
    stream: bool = False,
    mode: SpeakTurnMode = "inbound",
    record: bool = True,
    interrupt_context: InterruptContext | None = None,
) -> SpeakTurnResult:
    from ..io.outbound.stream import parse_agent_output as default_parse
    from ..service import SpeakTurnResult

    parse = host.parse_agent_output or default_parse

    open_result = manager.open(session_id, trigger="user_message")
    notes = list(open_result.notes)
    if interrupt_context is not None:
        notes.append("session: user interrupt turn")

    manager.begin_push(session_id, user_text)
    partial_output = ""
    try:
        interactor_id = session_id
        if host.resolve_interactor_id is not None:
            interactor_id = host.resolve_interactor_id(session_id)
        if host.on_memory_activation is not None:
            host.on_memory_activation(session_id, interactor_id, user_text)

        bundle = host.compose_bundle(session_id, user_text, mode=mode)
        all_events: list[SpeakStreamEvent] = []
        answer = ""
        parsed: SpeakAgentOutput | None = None
        llm_user_text = bundle.user_text or user_text

        def _on_partial(partial: str) -> None:
            nonlocal partial_output
            partial_output = partial
            manager.update_partial_output(session_id, partial)

        max_rounds = 8
        for round_idx in range(max_rounds):
            system = bundle.build_system()
            if interrupt_context is not None:
                system = f"{system}\n\n{manager.render_interrupt_block(interrupt_context)}"
            if round_idx > 0 and parsed is not None and parsed.session_state == "append":
                system = f"{system}\n\n{_APPEND_CONTINUE_INSTRUCTION}"

            answer, events = _generate_with_outbound(
                host,
                session_id,
                llm_user_text,
                system=system,
                stream=stream,
                on_partial=_on_partial,
            )
            all_events.extend(events)
            parsed = parse(answer)

            if interrupt_context is not None and parsed.session_state in ("share", "recall"):
                notes.append(f"session_state: {parsed.session_state} suspended by interrupt")
                break

            handoff = _resolve_handoff(
                host,
                session_id,
                llm_user_text,
                system=system,
                stream=stream,
                parsed=parsed,
                notes=notes,
            )
            if handoff is not None:
                handoff_answer, handoff_events, parsed = handoff
                if handoff_answer.strip():
                    answer = handoff_answer
                    manager.update_partial_output(session_id, answer)
                    partial_output = answer.strip()
                all_events.extend(handoff_events)
                if parsed.session_state == "finish":
                    break
                continue

            if parsed.session_state == "append":
                notes.append("session_state: append")
                continue

            if parsed.session_state in ("share", "recall"):
                break

            if parsed.session_state == "finish":
                break

            if manager.compose_queue.has_pending(session_id, mode=mode) and host.compose_from_queue is not None:
                queued = host.compose_from_queue(session_id, user_text, mode=mode)
                if queued is not None:
                    bundle = queued
                    notes.append("compose: queued push")
                    continue

            break
        else:
            notes.append("session: push round limit reached")

        if parsed is None:
            parsed = parse(answer)

        answer_body = parsed.speak or answer.strip()
        recorded = False
        if record and answer_body:
            chunk = SpeakTurnChunk(
                session_id=session_id,
                user_text=user_text,
                agent_text=answer_body,
                subjective=SpeakSubjectiveChunk(prior_thought=parsed.thought),
            )
            dispatch = manager.record_turn(
                chunk,
                on_after=lambda sid: host.schedule_compose(sid),
            )
            recorded = dispatch.recorded
            notes.extend(dispatch.notes)

        return SpeakTurnResult(
            session_id=session_id,
            answer=answer_body,
            bundle=bundle,
            output=parsed,
            stream_events=all_events,
            recorded=recorded,
            notes=notes,
            meta={
                "session_state": parsed.session_state,
                "interrupted": interrupt_context is not None,
            },
        )
    finally:
        manager.end_push(session_id, partial_output=partial_output)
