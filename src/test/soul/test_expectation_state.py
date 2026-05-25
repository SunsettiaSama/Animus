from __future__ import annotations

from agent.soul.presence.fsm.expectation import (
    PROACTIVE_OPEN_THRESHOLD,
    REPLY_URGE_THRESHOLD,
    ExpectationState,
)
from agent.soul.presence.fsm.state import PresenceState
from agent.soul.presence.interface.shared.events import CaptureEvent, CaptureKind
from agent.soul.presence.interface.ingress import apply_evolution_impulse
from agent.soul.presence.transition.interaction import PresenceInteraction


def test_expectation_state_accumulates_toward_user():
    exp = ExpectationState()
    exp.accumulate_toward_user(0.4, reason="想分享今天的事", source="story_beat")
    assert exp.toward_user == 0.4
    assert exp.reason == "想分享今天的事"
    assert exp.at_proactive_threshold() is False
    exp.accumulate_toward_user(0.3)
    assert exp.at_proactive_threshold(threshold=PROACTIVE_OPEN_THRESHOLD) is True


def test_expectation_state_reply_urge():
    exp = ExpectationState()
    exp.accumulate_reply_urge(0.4, reason="还没说完")
    assert exp.wants_multi_reply() is True
    exp.discharge_reply_urge(0.2)
    assert exp.reply_urge == 0.2
    assert exp.wants_multi_reply(threshold=REPLY_URGE_THRESHOLD) is False


def test_presence_state_persists_expectation():
    state = PresenceState()
    state.expectation.accumulate_toward_user(0.5, source="wander")
    state.expectation.accumulate_reply_urge(0.35)
    restored = PresenceState.from_dict(state.to_dict())
    assert restored.expectation.toward_user == 0.5
    assert restored.expectation.reply_urge == 0.35


def test_evolution_impulse_syncs_fsm_expectation():
    state = PresenceState()
    interaction = PresenceInteraction()
    event = CaptureEvent(
        kind=CaptureKind.story_beat,
        session_id="tao",
        payload={"hint": "路边下雨", "salience": 0.7, "share_desire": "eager"},
    )
    apply_evolution_impulse(interaction, event, state=state)
    assert state.expectation.toward_user > 0.0
    assert state.expectation.reply_urge > 0.0
    assert state.expectation.at_proactive_threshold() is True
