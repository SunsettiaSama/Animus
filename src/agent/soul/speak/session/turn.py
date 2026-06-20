from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..orchestrator import SpeakPromptBundle, SpeakTurnMode
from ..orchestrator.assemble import build_turn_system, resolve_llm_user_text
from ..orchestrator.prompt_trace import get_prompt_trace
from ..io.outbound.stream import SpeakAgentOutput, SpeakStreamEvent, SpeakStreamPipeline
from ..io.outbound.stream.channel import SpeakStreamChannel
from ..llm.engine import SpeakLLMEngine
from .chunk import SpeakSubjectiveChunk, SpeakTurnChunk
from .queue.types import InterruptContext
from .service import SpeakSessionService
from .working_memory_text import format_agent_turn_for_working_memory

if TYPE_CHECKING:
    from ..service import SpeakTurnResult


def _parsed_from_stream_events(
    events: list[SpeakStreamEvent],
    parse: Callable[[str], SpeakAgentOutput],
) -> SpeakAgentOutput:
    finish = next((event for event in reversed(events) if event.kind == "finish"), None)
    if finish is not None and finish.meta:
        return SpeakAgentOutput.from_finish_meta(finish.meta, speak_fallback=finish.text)
    raw = finish.text if finish is not None else ""
    return parse(raw)


@dataclass
class SessionTurnHost:
    compose_bundle: Callable[..., SpeakPromptBundle]
    begin_turn: Callable[[str], int]
    llm: SpeakLLMEngine
    stream_pipeline: SpeakStreamPipeline
    outbound_stream: SpeakStreamChannel
    record_turn: Callable[[SpeakTurnChunk], Any]
    schedule_compose: Callable[[str], None]
    refresh_similar_memories: Callable[..., None] | None = None
    refresh_interactor_portrait: Callable[..., None] | None = None
    resolve_interactor_id: Callable[[str], str] | None = None
    continue_share_handoff: Callable[..., tuple[str, list[SpeakStreamEvent], "SpeakAgentOutput"] | None] | None = None
    continue_recall_handoff: Callable[..., tuple[str, list[SpeakStreamEvent], "SpeakAgentOutput"] | None] | None = None
    compose_from_queue: Callable[..., SpeakPromptBundle | None] | None = None
    parse_agent_output: Callable[[str], SpeakAgentOutput] | None = None
    session_trace_cache: Callable[[str, int], dict] | None = None
    on_turn_start: Callable[[str, str, int], None] | None = None
    before_compose_bundle: Callable[[str, str], None] | None = None
    on_turn_complete_hook: Callable[[str, str, str, int, str], None] | None = None


def _generate_with_outbound(
    host: SessionTurnHost,
    session_id: str,
    user_text: str,
    *,
    system: str,
    stream: bool,
    on_partial: Callable[[str], None] | None = None,
) -> tuple[SpeakAgentOutput, list[SpeakStreamEvent]]:
    parse = host.parse_agent_output
    from ..io.outbound.stream import parse_agent_output as default_parse

    if parse is None:
        parse = default_parse
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
        finish = next((event for event in reversed(events) if event.kind == "finish"), None)
        answer = finish.text if finish is not None else ""
        if on_partial is not None:
            spoken = ""
            for event in events:
                if event.kind == "speak":
                    spoken += event.text
                    on_partial(spoken)
            if answer.strip():
                on_partial(answer.strip())
        parsed = _parsed_from_stream_events(events, parse)
        return parsed, events

    llm_result = host.llm.generate(user_text, system=system)
    answer = llm_result.text
    if on_partial is not None and answer.strip():
        on_partial(answer.strip())
    events = list(host.stream_pipeline.emit_parsed_output(session_id, answer))
    return parse(answer), events


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

    turn_index = host.begin_turn(session_id)
    notes.append(f"session: turn_index={turn_index}")

    if host.on_turn_start is not None:
        host.on_turn_start(session_id, user_text, turn_index)

    manager.begin_push(session_id, user_text)
    partial_output = ""
    try:
        if host.before_compose_bundle is not None:
            host.before_compose_bundle(session_id, user_text)
        bundle = host.compose_bundle(session_id, user_text, mode=mode, turn_index=turn_index)
        all_events: list[SpeakStreamEvent] = []
        parsed: SpeakAgentOutput | None = None
        speak_parts: list[str] = []
        memory_parts: list[str] = []
        silence_policy: str | None = None
        llm_user_text = resolve_llm_user_text(bundle, user_text)

        def _on_partial(partial: str) -> None:
            nonlocal partial_output
            partial_output = partial
            manager.update_partial_output(session_id, partial)

        max_rounds = 8
        for round_idx in range(max_rounds):
            if host.refresh_interactor_portrait is not None:
                host.refresh_interactor_portrait(session_id, bundle, turn_index)
            system = build_turn_system(
                bundle,
                interrupt_context=interrupt_context,
                round_idx=round_idx,
                partial_output=partial_output,
                parsed=parsed,
            )
            llm_user_text = resolve_llm_user_text(
                bundle,
                user_text,
                round_idx=round_idx,
                parsed=parsed,
            )

            if host.session_trace_cache is not None:
                get_prompt_trace().emit_compose(
                    session_id,
                    turn_index=turn_index,
                    bundle=bundle,
                    cache=host.session_trace_cache(session_id, turn_index),
                    round_idx=round_idx,
                    system_override=system,
                )

            parsed_round, events = _generate_with_outbound(
                host,
                session_id,
                llm_user_text,
                system=system,
                stream=stream,
                on_partial=_on_partial,
            )
            all_events.extend(events)
            parsed = parsed_round
            round_memory = format_agent_turn_for_working_memory(parsed.blocks)
            if round_memory:
                memory_parts.append(round_memory)
            if parsed.speak.strip():
                speak_parts.append(parsed.speak.strip())
                partial_output = "\n".join(speak_parts)
                manager.update_partial_output(session_id, partial_output)

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
                handoff_memory = format_agent_turn_for_working_memory(
                    parsed.blocks,
                    speak_fallback=handoff_answer,
                )
                if handoff_memory:
                    memory_parts.append(handoff_memory)
                if handoff_answer.strip():
                    manager.update_partial_output(session_id, handoff_answer)
                    partial_output = handoff_answer.strip()
                    speak_parts = [handoff_answer.strip()]
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

            if host.compose_from_queue is not None:
                queued = host.compose_from_queue(
                    session_id,
                    user_text,
                    mode=mode,
                    turn_index=turn_index,
                )
                if queued is not None:
                    bundle = queued
                    notes.append("compose: queued push")
                    continue

            break
        else:
            notes.append("session: push round limit reached")

        if parsed is None:
            parsed = SpeakAgentOutput()

        answer_body = "\n".join(speak_parts).strip() if speak_parts else (parsed.speak or "").strip()
        memory_agent_text = "\n\n".join(part for part in memory_parts if part.strip()).strip()
        if not memory_agent_text and parsed is not None:
            memory_agent_text = format_agent_turn_for_working_memory(
                parsed.blocks,
                speak_fallback=answer_body,
            )
        if (
            mode == "inbound"
            and not answer_body.strip()
            and parsed.session_state == "finish"
            and not interrupt_context
        ):
            from .silence_policy import apply_empty_speak_policy

            silence_policy, answer_body, silence_events = apply_empty_speak_policy(
                session_id=session_id,
                pipeline=host.stream_pipeline,
                stream=stream,
            )
            all_events.extend(silence_events)
            if silence_policy == "ellipsis":
                notes.append("silence_policy: ellipsis")
            else:
                notes.append("silence_policy: hidden")

        recorded = False
        agent_text_for_memory = memory_agent_text or answer_body
        if record and agent_text_for_memory.strip():
            memory_ids = list(bundle.meta.get("activated_memory_ids", []))
            spill = bundle.meta.get("memory_spill")
            if isinstance(spill, dict):
                memory_ids.extend(list(spill.get("unit_ids", [])))
            chunk = SpeakTurnChunk(
                session_id=session_id,
                user_text=user_text,
                agent_text=agent_text_for_memory,
                subjective=SpeakSubjectiveChunk(prior_thought=parsed.thought),
                activated_memory_ids=list(dict.fromkeys(memory_ids)),
            )
            dispatch = manager.record_turn(
                chunk,
                on_after=lambda sid: host.schedule_compose(sid),
            )
            recorded = dispatch.recorded
            notes.extend(dispatch.notes)
            if host.refresh_similar_memories is not None:
                host.refresh_similar_memories(
                    session_id,
                    turn_index=turn_index,
                    user_text=user_text,
                    agent_text=answer_body,
                )

        if host.session_trace_cache is not None:
            get_prompt_trace().emit_turn_finish(
                session_id,
                turn_index=turn_index,
                parsed=parsed,
                answer=answer_body,
                notes=notes,
                cache=host.session_trace_cache(session_id, turn_index),
            )

        manager.on_turn_complete(
            session_id,
            mode=mode,
            session_state=parsed.session_state,
            answer=answer_body,
        )
        if host.on_turn_complete_hook is not None:
            host.on_turn_complete_hook(
                session_id,
                user_text,
                answer_body,
                turn_index,
                parsed.session_state,
            )

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
                "turn_index": turn_index,
                "silence_policy": silence_policy,
            },
        )
    finally:
        manager.end_push(session_id, partial_output=partial_output)
