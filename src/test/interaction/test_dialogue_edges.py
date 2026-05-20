from __future__ import annotations

from agent.interaction.core.expectation import Expectation
from agent.soul.drive import (
    DriveContext,
    DriveEvent,
    DriveState,
    apply_transition,
    match_drive_edge,
)


def test_match_edge_user_text_closed():
    edge = match_drive_edge(
        DriveState(),
        DriveContext(),
        DriveEvent.user_text("tao", ambiguous=False),
    )
    assert edge is not None
    assert edge.id == "user_text.closed.open.required"


def test_inbound_path_user_then_agent_final():
    state = DriveState()
    result = apply_transition(
        state,
        DriveEvent.user_text("tao", ambiguous=False),
        DriveContext(line_open=False),
    )
    assert result.after.expectation == Expectation.required

    result = apply_transition(
        state,
        DriveEvent.agent_utterance("tao", final=True),
        DriveContext(line_open=True),
    )
    assert result.after.expectation == Expectation.none
    assert "none" in result.notes[-1]


def test_outbound_path_proactive_then_user_reply():
    state = DriveState()
    apply_transition(
        state,
        DriveEvent.proactive_open("tao", wait_reply=True),
        DriveContext(),
    )
    assert state.expectation == Expectation.required

    apply_transition(
        state,
        DriveEvent.proactive_delivered("tao"),
        DriveContext(line_open=True),
    )
    assert state.expectation == Expectation.required

    result = apply_transition(
        state,
        DriveEvent.user_text("tao", proactive_intent_id="pi-1"),
        DriveContext(line_open=True, proactive_intent_id="pi-1"),
    )
    assert result.after.expectation == Expectation.required
    assert "proactive intent answered" in result.notes[-1]
