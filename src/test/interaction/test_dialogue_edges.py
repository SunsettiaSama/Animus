from __future__ import annotations

from agent.interaction.core.expectation import Expectation
from agent.soul.presence import (
    PresenceContext,
    PresenceEvent,
    PresenceState,
    apply_transition,
    match_presence_edge,
)
from agent.soul.presence.fsm import BehaviorState


def test_match_edge_user_text_closed():
    edge = match_presence_edge(
        PresenceState(),
        PresenceContext(),
        PresenceEvent.user_text("tao", ambiguous=False),
    )
    assert edge is not None
    assert edge.id == "user_text.closed.open.required"


def test_inbound_path_user_then_agent_final():
    state = PresenceState()
    result = apply_transition(
        state,
        PresenceEvent.user_text("tao", ambiguous=False),
        PresenceContext(line_open=False),
    )
    assert result.after.behavior.expectation == Expectation.required

    result = apply_transition(
        state,
        PresenceEvent.agent_utterance("tao", final=True),
        PresenceContext(line_open=True),
    )
    assert result.after.behavior.expectation == Expectation.none
    assert "none" in result.notes[-1]


def test_outbound_path_proactive_then_user_reply():
    state = PresenceState()
    apply_transition(
        state,
        PresenceEvent.proactive_open("tao", wait_reply=True),
        PresenceContext(),
    )
    assert state.behavior.expectation == Expectation.required

    apply_transition(
        state,
        PresenceEvent.proactive_delivered("tao"),
        PresenceContext(line_open=True),
    )
    assert state.behavior.expectation == Expectation.required

    result = apply_transition(
        state,
        PresenceEvent.user_text("tao", proactive_intent_id="pi-1"),
        PresenceContext(line_open=True, proactive_intent_id="pi-1"),
    )
    assert result.after.behavior.expectation == Expectation.required
    assert "proactive intent answered" in result.notes[-1]
