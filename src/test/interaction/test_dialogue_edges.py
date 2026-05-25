from __future__ import annotations

from agent.interaction.core.expectation import Expectation
from agent.soul.presence import PresenceContext, PresenceEvent, PresenceState
from agent.soul.presence.transition import PresenceInteraction, apply_transition, match_presence_edge


def test_match_edge_user_text_closed():
    edge = match_presence_edge(
        PresenceInteraction(),
        PresenceContext(),
        PresenceEvent.user_text("tao", ambiguous=False),
    )
    assert edge is not None
    assert edge.id == "user_text.closed.open.required"


def test_inbound_path_user_then_agent_final():
    state = PresenceState()
    interaction = PresenceInteraction()
    result = apply_transition(
        state,
        interaction,
        PresenceEvent.user_text("tao", ambiguous=False),
        PresenceContext(line_open=False),
    )
    assert result.interaction_after.expectation == Expectation.required

    result = apply_transition(
        state,
        interaction,
        PresenceEvent.agent_utterance("tao", final=True),
        PresenceContext(line_open=True),
    )
    assert result.interaction_after.expectation == Expectation.none
    assert "none" in result.notes[-1]


def test_outbound_path_proactive_then_user_reply():
    state = PresenceState()
    interaction = PresenceInteraction()
    apply_transition(
        state,
        interaction,
        PresenceEvent.proactive_open("tao", wait_reply=True),
        PresenceContext(),
    )
    assert interaction.expectation == Expectation.required

    apply_transition(
        state,
        interaction,
        PresenceEvent.proactive_delivered("tao"),
        PresenceContext(line_open=True),
    )
    assert interaction.expectation == Expectation.required

    result = apply_transition(
        state,
        interaction,
        PresenceEvent.user_text("tao", proactive_intent_id="pi-1"),
        PresenceContext(line_open=True, proactive_intent_id="pi-1"),
    )
    assert result.interaction_after.expectation == Expectation.required
    assert "proactive intent answered" in result.notes[-1]
