from __future__ import annotations

from dataclasses import dataclass, field

from ..fsm.events import PresenceEvent, PresenceEventKind
from ..fsm.state import PresenceContext, PresenceState
from .edges import match_presence_edge


@dataclass
class TransitionResult:
    session_id: str
    event: PresenceEvent
    before: PresenceState
    after: PresenceState
    notes: list[str] = field(default_factory=list)


def _apply_expectation_edge(
    state: PresenceState,
    context: PresenceContext,
    event: PresenceEvent,
) -> list[str]:
    before = state.copy()
    notes: list[str] = []

    edge = match_presence_edge(before, context, event)
    if edge is None:
        notes.append(f"presence: no edge for {event.kind.value}")
        return notes

    after = state.copy()
    if edge.mutate is not None:
        edge.mutate(after, before, context, event.payload)
    state.behavior.expectation = after.behavior.expectation

    if event.kind == PresenceEventKind.agent_utterance:
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
    state: PresenceState,
    event: PresenceEvent,
    context: PresenceContext,
) -> TransitionResult:
    """纯 FSM 期待转移（由 capture 在边界事件注入时调用）。"""
    before = state.copy()
    notes: list[str] = []
    kind = event.kind

    if kind == PresenceEventKind.close:
        state.reset()
        notes.append(f"presence reset via {kind.value}")
    else:
        notes.extend(_apply_expectation_edge(state, context, event))

    return TransitionResult(
        session_id=event.session_id,
        event=event,
        before=before,
        after=state.copy(),
        notes=notes,
    )


apply_presence_transition = apply_transition
