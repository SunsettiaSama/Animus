from __future__ import annotations

from agent.interaction.core.expectation import Expectation
from agent.posture import (
    InteractionEvent,
    InteractionPosture,
)


def test_user_opens_then_agent_questions():
    posture = InteractionPosture()
    r1 = posture.dispatch(InteractionEvent.user_text("tao", "帮我分析风险"))
    assert r1.after.line_open is True

    r2 = posture.dispatch(
        InteractionEvent.agent_utterance("tao", has_question=True, final=True)
    )
    assert r2.after.line_open is True


def test_deferred_then_close():
    posture = InteractionPosture()
    posture.dispatch(InteractionEvent.user_text("tao", "查一�?))
    posture.dispatch(InteractionEvent.agent_deferred("tao"))

    r2 = posture.dispatch(InteractionEvent.close("tao"))
    assert r2.after.line_open is False
    assert r2.after.proactive_intent_id == ""


def test_scene_enter_while_idle():
    posture = InteractionPosture()
    r = posture.dispatch(
        InteractionEvent.scene_enter("tao", scene_id="room-1", admitted=True)
    )
    assert r.after.in_scene is True
    assert r.after.scene_admitted is True
    assert r.after.line_open is True


def test_dialogue_kernel_syncs_presence_expectation():
    from agent.interaction.dialogue import DialogueKernel
    from agent.soul.presence import PresenceService, Expectation

    presence_svc = PresenceService()
    k = DialogueKernel(presence=presence_svc)
    k.on_user_text("tao", "你好")
    assert k.presence.snapshot("tao").expectation == Expectation.required
