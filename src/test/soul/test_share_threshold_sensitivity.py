"""分享 / 主动开口：改为 agent push 标注驱动，不再依赖 toward_user 硬阈值。"""
from __future__ import annotations

from unittest.mock import MagicMock

from agent.soul.presence.share_desire import ShareDesire, share_desire_weight
from agent.soul.presence.state.dynamic.expectation import (
    ExpectationState,
    apply_non_dialogue_share_refresh,
    scan_expectation_thresholds,
)
from agent.soul.presence.state.dynamic.expectation.scanner import ExpectationScanMode
from agent.soul.presence.transition.interaction import PresenceInteraction
from agent.soul.presence.service import PresenceService


def test_enqueue_without_push_does_not_proactive_scan():
    exp = ExpectationState()
    interaction = PresenceInteraction()
    apply_non_dialogue_share_refresh(
        exp,
        interaction,
        {
            "enqueue_share": "true",
            "share_content": "今天有个想法",
            "share_desire": "moderate",
        },
        source="life:experience",
    )
    scan = scan_expectation_thresholds(
        session_id="tao",
        expectation=exp,
        interaction=interaction,
        line_open=False,
    )
    assert exp.toward_user == share_desire_weight(ShareDesire.moderate)
    assert exp.pending_push is False
    assert scan.triggered is False


def test_push_to_user_triggers_proactive_scan():
    exp = ExpectationState()
    interaction = PresenceInteraction()
    apply_non_dialogue_share_refresh(
        exp,
        interaction,
        {
            "enqueue_share": "true",
            "push_to_user": "true",
            "share_content": "很想告诉你这件事",
            "share_desire": "mild",
            "share_why": "忍不住",
        },
        source="life:experience",
    )
    scan = scan_expectation_thresholds(
        session_id="tao",
        expectation=exp,
        interaction=interaction,
        line_open=False,
    )
    assert scan.triggered is True
    assert scan.mode == ExpectationScanMode.proactive_open
    assert exp.pending_push is True


def test_push_only_still_queues_for_consume():
    exp = ExpectationState()
    interaction = PresenceInteraction()
    apply_non_dialogue_share_refresh(
        exp,
        interaction,
        {
            "push_to_user": "true",
            "share_content": "一次性推送",
            "share_desire": "eager",
        },
        source="life:experience",
    )
    assert len(exp.share_queue) == 1
    assert exp.share_queue[0].push_to_user is True
    scan = scan_expectation_thresholds(
        session_id="chan",
        expectation=exp,
        interaction=interaction,
        line_open=False,
    )
    assert scan.triggered is True


def test_discharge_skips_impulse_gate_when_push_ready():
    svc = PresenceService()
    session = svc._session("chan")
    apply_non_dialogue_share_refresh(
        session.state.expectation,
        session.interaction,
        {
            "push_to_user": "true",
            "share_content": "推送内容",
            "share_desire": "mild",
        },
        source="life:experience",
    )
    # mild 权重可能低于旧 moderate 门槛，但 push 应放行
    session.interaction.impulse_level = 0.1
    discharge = svc.discharge_accumulated("chan", require_saturated=True)
    assert discharge is not None
    assert "推送内容" in discharge.reason


def test_channel_store_archives_on_wake(tmp_path):
    svc = PresenceService(life_dir=str(tmp_path))
    session = svc._session("chan-a")
    apply_non_dialogue_share_refresh(
        session.state.expectation,
        session.interaction,
        {
            "enqueue_share": "true",
            "share_content": "别丢掉",
            "share_desire": "moderate",
        },
        source="life:experience",
    )
    svc._persist("chan-a")
    from agent.soul.presence.transition import PresenceTrigger

    svc.trigger(PresenceTrigger.wake("chan-a", force=True))
    assert svc.share_queue_size("chan-a") == 0
    archive = tmp_path / "channels" / "chan-a" / "share_archive.jsonl"
    assert archive.exists()
    assert "别丢掉" in archive.read_text(encoding="utf-8")
