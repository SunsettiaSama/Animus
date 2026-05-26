from __future__ import annotations

from dataclasses import dataclass, field

from ...state import PresenceContext, PresenceEvent, PresenceEventKind, PresenceState
from ..interaction import PresenceInteraction
from .edges import match_presence_edge


@dataclass
class TransitionResult:
    session_id: str
    event: PresenceEvent
    state_before: PresenceState
    state_after: PresenceState
    interaction_before: PresenceInteraction
    interaction_after: PresenceInteraction
    notes: list[str] = field(default_factory=list)

    @property
    def before(self) -> PresenceState:
        return self.state_before

    @property
    def after(self) -> PresenceState:
        return self.state_after


def _apply_expectation_edge(
    state: PresenceState,
    interaction: PresenceInteraction,
    context: PresenceContext,
    event: PresenceEvent,
) -> list[str]:
    before = interaction.copy()
    notes: list[str] = []

    edge = match_presence_edge(before, context, event)
    if edge is None:
        notes.append(f"presence: no edge for {event.kind.value}")
        return notes

    after = interaction.copy()
    if edge.mutate is not None:
        edge.mutate(after, before, context, event.payload)
    interaction.expectation = after.expectation

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


def apply_boundary_transition(
    state: PresenceState,
    interaction: PresenceInteraction,
    event: PresenceEvent,
    context: PresenceContext,
) -> TransitionResult:
    state_before = state.copy()
    interaction_before = interaction.copy()
    notes: list[str] = []
    kind = event.kind

    if kind == PresenceEventKind.close:
        interaction.reset()
        notes.append(f"presence reset via {kind.value}")
    else:
        notes.extend(_apply_expectation_edge(state, interaction, context, event))

    return TransitionResult(
        session_id=event.session_id,
        event=event,
        state_before=state_before,
        state_after=state.copy(),
        interaction_before=interaction_before,
        interaction_after=interaction.copy(),
        notes=notes,
    )


apply_transition = apply_boundary_transition
apply_presence_transition = apply_boundary_transition
