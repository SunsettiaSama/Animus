from __future__ import annotations

from agent.soul.presence import (
    CaptureEvent,
    PresenceContext,
    PresenceEvent,
    PresenceState,
    ShareDesire,
    capture_event_from_presence,
)
from agent.soul.presence.fsm.expectation import enqueue_capture_event
from agent.soul.presence.interface.egress import SpeakInterface
from agent.soul.presence.interface.ingress import apply_evolution_impulse
from agent.soul.presence.transition import PresenceInteraction, apply_transition
from agent.soul.presence.share_desire import share_desire_weight


def test_apply_evolution_impulse_uses_share_desire_weight():
    interaction = PresenceInteraction()
    note = apply_evolution_impulse(
        interaction,
        CaptureEvent.wander(
            "tao",
            hint="反刍线索",
            salience=0.4,
            share_desire=ShareDesire.moderate,
        ),
    )
    assert interaction.impulse_level == share_desire_weight(ShareDesire.moderate)
    assert interaction.share_desire == ShareDesire.moderate
    assert interaction.impulse_reason == "反刍线索"
    assert "wander" in note


def test_mild_share_desire_accumulates_slowly():
    interaction = PresenceInteraction()
    state = PresenceState()
    apply_evolution_impulse(
        interaction,
        CaptureEvent.story_beat(
            "tao",
            hint="一点念头",
            share_desire=ShareDesire.mild,
        ),
        state=state,
    )
    assert interaction.impulse_level == share_desire_weight(ShareDesire.mild)
    assert SpeakInterface().evaluate(
        session_id="tao",
        interaction=interaction.copy(),
        expectation=state.expectation,
    ) is None


def test_transition_routes_boundary_user_text():
    state = PresenceState()
    interaction = PresenceInteraction()
    result = apply_transition(
        state,
        interaction,
        PresenceEvent.user_text("tao"),
        PresenceContext(line_open=False),
    )
    assert interaction.expectation.value == "required"
    assert result.notes


def test_evolution_impulse_for_landmark():
    interaction = PresenceInteraction()
    apply_evolution_impulse(
        interaction,
        CaptureEvent.landmark("tao", intention="去海边走走"),
    )
    assert interaction.impulse_level == 0.0
    assert interaction.share_desire == ShareDesire.none
    assert "海边" in interaction.impulse_reason


def test_gate_breaks_on_eager_share_desire():
    interaction = PresenceInteraction()
    state = PresenceState()
    event = CaptureEvent.wander(
        "tao",
        hint="想说话",
        salience=0.8,
        share_desire=ShareDesire.eager,
    )
    apply_evolution_impulse(interaction, event, state=state)
    enqueue_capture_event(state.expectation, event)
    outbound = SpeakInterface().evaluate(
        session_id="tao",
        interaction=interaction,
        expectation=state.expectation,
    )
    assert outbound is not None
    assert outbound.reason == "想说话"
    assert outbound.share_desire == ShareDesire.eager
    assert outbound.package.count == 1


def test_gate_breaks_after_multiple_mild_events():
    interaction = PresenceInteraction()
    state = PresenceState()
    for hint in ("慢慢想说", "还有一件", "第三件", "第四件"):
        event = CaptureEvent.story_beat(
            "tao",
            hint=hint,
            salience=0.4,
            share_desire=ShareDesire.mild,
        )
        apply_evolution_impulse(interaction, event, state=state)
        enqueue_capture_event(state.expectation, event)
    event = CaptureEvent.story_beat(
        "tao",
        hint="慢慢想说",
        share_desire=ShareDesire.mild,
    )
    apply_evolution_impulse(interaction, event, state=state)
    enqueue_capture_event(state.expectation, event)
    outbound = SpeakInterface().evaluate(
        session_id="tao",
        interaction=interaction,
        expectation=state.expectation,
    )
    assert outbound is not None
    assert outbound.package.count == 5
    assert "另有" in outbound.reason
    assert outbound.share_desire in (ShareDesire.mild, ShareDesire.moderate, ShareDesire.eager)


def test_capture_event_from_presence():
    event = capture_event_from_presence(PresenceEvent.user_text("tao"))
    assert event.session_id == "tao"
