from __future__ import annotations

from agent.interaction.core.expectation import Expectation
from agent.interaction.kinds import InteractionModalityKind
from agent.posture.events import InteractionEvent
from agent.posture.fsm import (
    DialogueStance,
    PostureFsmState,
    apply_dialogue_transition,
    apply_transition,
)
from agent.soul.presence import PresenceContext, PresenceEvent, PresenceState, apply_transition as apply_presence
from agent.soul.presence.fsm import BehaviorState


def test_apply_dialogue_transition_user_text_from_idle():
    dialogue = DialogueStance()
    after, notes = apply_dialogue_transition(
        dialogue, InteractionEvent.user_text("tao", "你好")
    )
    assert after.line_open is True
    assert "line opened" in notes[-1]


def test_apply_transition_user_text_from_idle():
    state = PostureFsmState.empty()
    result = apply_transition(
        state, InteractionEvent.user_text("tao", "你好")
    )
    assert result.after.dialogue.line_open is True


def test_presence_user_text_from_idle_sets_required():
    state = PresenceState()
    result = apply_presence(
        state,
        PresenceEvent.user_text("tao"),
        PresenceContext(line_open=False),
    )
    assert result.after.behavior.expectation == Expectation.required


def test_presence_user_text_ambiguous_to_clarify():
    state = PresenceState()
    result = apply_presence(
        state,
        PresenceEvent.user_text("tao", ambiguous=True),
        PresenceContext(line_open=True),
    )
    assert result.after.behavior.expectation == Expectation.clarify


def test_presence_clarify_resolved():
    state = PresenceState(behavior=BehaviorState(expectation=Expectation.clarify))
    result = apply_presence(
        state,
        PresenceEvent.clarify_resolved("tao"),
        PresenceContext(),
    )
    assert result.after.behavior.expectation == Expectation.required


def test_apply_transition_proactive_open():
    state = PostureFsmState.empty()
    r1 = apply_transition(
        state,
        InteractionEvent.proactive_open(
            "tao", wait_reply=True, intent_id="pi-1"
        ),
    )
    assert r1.after.dialogue.line_open is True
    assert r1.after.dialogue.proactive_intent_id == "pi-1"


def test_apply_transition_scene_enter_with_admission():
    state = PostureFsmState.empty()
    result = apply_transition(
        state,
        InteractionEvent.scene_enter(
            "tao",
            scene_id="room-1",
            scene_kind="room",
            title="作战室",
            stakes="查风险",
            admitted=True,
        ),
    )
    assert result.after.scene.in_scene is True
    assert result.after.scene.scene_admitted is True
    assert result.after.scene.scene_kind == "room"
    assert result.after.scene.stakes == "查风险"
    assert result.after.dialogue.line_open is True


def test_apply_transition_scene_enter_pending_admission():
    state = PostureFsmState.empty()
    result = apply_transition(
        state, InteractionEvent.scene_enter("tao", scene_id="evt-1", admitted=False)
    )
    assert result.after.scene.in_scene is True
    assert result.after.scene.scene_admitted is False


def test_apply_transition_terminate_resets_fsm_fields():
    state = PostureFsmState.empty()
    state.dialogue.line_open = True
    state.dialogue.proactive_intent_id = "pi-1"
    state.scene.in_scene = True
    state.scene.scene_admitted = True
    state.scene.scene_id = "room-1"
    state.session.interaction_id = "ix-1"
    state.scene.stakes = "high"
    state.session.primary_modality = InteractionModalityKind.dialogue.value
    state.session.drone_ref = "drone-1"
    result = apply_transition(state, InteractionEvent.close("tao"))
    assert result.after.dialogue.line_open is False
    assert result.after.dialogue.proactive_intent_id == ""
    assert result.after.scene.in_scene is False
    assert result.after.session.drone_ref == ""
