from __future__ import annotations

from dataclasses import dataclass, field

from ..fsm.events import DriveEvent, DriveEventKind
from ..fsm.state import DriveContext, DriveState
from .edges import match_drive_edge


@dataclass
class TransitionResult:
    session_id: str
    event: DriveEvent
    before: DriveState
    after: DriveState
    notes: list[str] = field(default_factory=list)


def _apply_expectation_edge(
    state: DriveState,
    context: DriveContext,
    event: DriveEvent,
) -> list[str]:
    before = state.copy()
    notes: list[str] = []

    edge = match_drive_edge(before, context, event)
    if edge is None:
        notes.append(f"drive: no edge for {event.kind.value}")
        return notes

    after = state.copy()
    if edge.mutate is not None:
        edge.mutate(after, before, context, event.payload)
    state.expectation = after.expectation

    if event.kind == DriveEventKind.agent_utterance:
        p = event.payload
        if p.get("notify_only"):
            notes.append("agent notify → optional")
        elif p.get("has_question"):
            notes.append("agent question → required")
        elif p.get("final"):
            notes.append("agent final → none")
        else:
            notes.append("agent partial → deferred")
    else:
        notes.append(edge.note)

    return notes


def apply_transition(
    state: DriveState,
    event: DriveEvent,
    context: DriveContext,
) -> TransitionResult:
    """纯 FSM 期待转移（由 capture 在边界事件注入时调用）。"""
    before = state.copy()
    notes: list[str] = []
    kind = event.kind

    if kind == DriveEventKind.close:
        state.reset()
        notes.append(f"drive reset via {kind.value}")
    else:
        notes.extend(_apply_expectation_edge(state, context, event))

    return TransitionResult(
        session_id=event.session_id,
        event=event,
        before=before,
        after=state.copy(),
        notes=notes,
    )


apply_drive_transition = apply_transition
