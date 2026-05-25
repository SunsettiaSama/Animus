from __future__ import annotations

from agent.soul.presence.fsm.expectation import (
    PROACTIVE_OPEN_THRESHOLD,
    REPLY_URGE_THRESHOLD,
    ExpectationScanMode,
    ExpectationState,
    ShareIntent,
    ShareIntentQueue,
    apply_non_dialogue_share_refresh,
    parse_dialogue_expectation,
    scan_expectation_thresholds,
)
from agent.soul.presence.fsm.expectation.intent import apply_dialogue_interaction_expectation
from agent.soul.presence.interface.egress.request import SpeakRequest
from agent.soul.presence.share_desire import ShareDesire
from agent.soul.presence.transition.expectation import Expectation
from agent.soul.presence.transition.interaction import PresenceInteraction
from agent.soul.presence.service import PresenceService


def test_share_intent_queue_fold_summary():
    queue = ShareIntentQueue()
    queue.enqueue(ShareIntent(topic="今天下雨了", share_desire=ShareDesire.moderate, salience=0.6))
    queue.enqueue(ShareIntent(topic="想到一段旧记忆", share_desire=ShareDesire.mild, salience=0.3))
    assert "今天下雨了" in queue.fold_summary()
    assert "另有 1 条" in queue.fold_summary()


def test_apply_non_dialogue_share_refresh_queues_and_accumulates():
    exp = ExpectationState()
    interaction = PresenceInteraction()
    notes = apply_non_dialogue_share_refresh(
        exp,
        interaction,
        {
            "wants_to_share": "true",
            "share_topic": "想分享地标兑现后的感受",
            "share_desire": "eager",
        },
        source="incident:surprise",
    )
    assert notes
    assert len(exp.share_queue.items) == 1
    assert exp.at_proactive_threshold() is True
    assert interaction.share_desire == ShareDesire.eager


def test_parse_dialogue_expectation_follow_up():
    assert parse_dialogue_expectation({"wants_follow_up_reply": "true"}) == Expectation.required
    assert parse_dialogue_expectation({"dialogue_expectation": "optional"}) == Expectation.optional


def test_scan_proactive_open_when_threshold_and_queue():
    exp = ExpectationState()
    exp.share_queue.enqueue(ShareIntent(topic="想和用户聊聊", share_desire=ShareDesire.eager))
    exp.accumulate_toward_user(PROACTIVE_OPEN_THRESHOLD, reason="想和用户聊聊")
    interaction = PresenceInteraction()
    scan = scan_expectation_thresholds(
        session_id="tao",
        expectation=exp,
        interaction=interaction,
        line_open=False,
    )
    assert scan.triggered is True
    assert scan.mode == ExpectationScanMode.proactive_open
    assert scan.speak_request is not None
    assert scan.speak_request.wait_reply is True


def test_scan_append_message_when_line_open_and_reply_urge():
    exp = ExpectationState()
    exp.share_queue.enqueue(ShareIntent(topic="还没说完", share_desire=ShareDesire.moderate))
    exp.accumulate_reply_urge(REPLY_URGE_THRESHOLD, reason="还没说完")
    interaction = PresenceInteraction(expectation=Expectation.required)
    scan = scan_expectation_thresholds(
        session_id="tao",
        expectation=exp,
        interaction=interaction,
        line_open=True,
    )
    assert scan.triggered is True
    assert scan.mode == ExpectationScanMode.append_message
    assert scan.speak_request is not None
    assert scan.speak_request.wait_reply is False


def test_presence_service_scan_expectation_drives_emits_speak_request():
    requests: list[SpeakRequest] = []
    svc = PresenceService(on_speak_request=requests.append)
    session = svc._session("tao")
    session.state.expectation.share_queue.enqueue(
        ShareIntent(topic="想主动说件事", share_desire=ShareDesire.eager)
    )
    session.state.expectation.accumulate_toward_user(PROACTIVE_OPEN_THRESHOLD)

    scan = svc.scan_expectation_drives("tao")
    assert scan.triggered is True
    assert len(requests) == 1
    assert requests[0].reason
    assert session.state.expectation.share_queue.is_empty()


def test_apply_dialogue_interaction_expectation_updates_interaction():
    interaction = PresenceInteraction()
    notes = apply_dialogue_interaction_expectation(
        interaction,
        {"dialogue_expectation": "required"},
    )
    assert notes
    assert interaction.expectation == Expectation.required
