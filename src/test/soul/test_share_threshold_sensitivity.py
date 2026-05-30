"""分享 / 主动开口阈值敏感性：量化默认配置下各路径是否可达。"""
from __future__ import annotations

from unittest.mock import MagicMock

from agent.soul.presence.share_desire import ShareDesire, share_desire_weight
from agent.soul.presence.state.dynamic.expectation import (
    PROACTIVE_OPEN_THRESHOLD,
    REPLY_URGE_THRESHOLD,
    ExpectationState,
    ShareIntent,
    ShareIntentQueue,
    apply_non_dialogue_share_refresh,
    scan_expectation_thresholds,
)
from agent.soul.presence.state.dynamic.expectation.scanner import ExpectationScanMode
from agent.soul.presence.transition.expectation import Expectation
from agent.soul.presence.transition.interaction import PresenceInteraction
from agent.soul.presence.service import PresenceService
from agent.soul.speak.compose.share import ShareDesireComposer
from config.soul.presence.config import OUTBOUND_THRESHOLD_MODERATE


def _mock_snap(*, toward_user: float, impulse: float, queue: ShareIntentQueue):
    snap = MagicMock()
    exp = ExpectationState(toward_user=toward_user, share_queue=queue)
    snap.state.expectation = exp
    snap.interaction.impulse_level = impulse
    snap.interaction.impulse_reason = ""
    snap.interaction.share_desire = ShareDesire.none
    return snap


def test_life_typical_single_moderate_does_not_trigger_proactive_scan():
    """单条 salience≈0.5 的 life 体验 → moderate(+0.35)，scan 仍不 proactive。"""
    exp = ExpectationState()
    interaction = PresenceInteraction()
    apply_non_dialogue_share_refresh(
        exp,
        interaction,
        {
            "wants_to_share": "true",
            "share_topic": "今天有个想法",
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
    assert exp.toward_user < PROACTIVE_OPEN_THRESHOLD
    assert scan.triggered is False


def test_life_eager_or_double_moderate_triggers_proactive_scan():
    exp = ExpectationState()
    interaction = PresenceInteraction()
    apply_non_dialogue_share_refresh(
        exp,
        interaction,
        {
            "wants_to_share": "true",
            "share_topic": "很想说",
            "share_desire": "eager",
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

    exp2 = ExpectationState()
    interaction2 = PresenceInteraction()
    for _ in range(2):
        apply_non_dialogue_share_refresh(
            exp2,
            interaction2,
            {
                "wants_to_share": "true",
                "share_topic": "片段",
                "share_desire": "moderate",
            },
            source="life:experience",
        )
    scan2 = scan_expectation_thresholds(
        session_id="tao",
        expectation=exp2,
        interaction=interaction2,
        line_open=False,
    )
    assert scan2.triggered is True
    assert scan2.mode == ExpectationScanMode.proactive_open


def test_drive_should_speak_lower_than_scan_proactive():
    """evaluate_drive 在 impulse≥0.35 即 True，但 scan proactive 要 toward_user≥0.65。"""
    queue = ShareIntentQueue(
        items=[ShareIntent(topic="想聊", share_desire=ShareDesire.moderate)],
    )
    snap = _mock_snap(toward_user=0.35, impulse=0.35, queue=queue)
    eval_result = ShareDesireComposer().evaluate_drive(snap)
    scan = scan_expectation_thresholds(
        session_id="tao",
        expectation=snap.state.expectation,
        interaction=PresenceInteraction(),
        line_open=False,
    )
    assert eval_result.should_speak is True
    assert scan.triggered is False


def test_discharge_blocked_until_impulse_moderate_threshold():
    svc = PresenceService()
    session = svc._session("tao")
    session.state.expectation.share_queue.enqueue(
        ShareIntent(topic="有话想说", share_desire=ShareDesire.mild),
    )
    session.interaction.impulse_level = 0.2
    assert svc.discharge_accumulated("tao", require_saturated=True) is None

    session.interaction.impulse_level = OUTBOUND_THRESHOLD_MODERATE
    discharge = svc.discharge_accumulated("tao", require_saturated=True)
    assert discharge is not None


def test_threshold_table_documented_gaps():
    """打印式断言：记录各档位累计 toward_user 与 scan/drive 关系。"""
    mild = share_desire_weight(ShareDesire.mild)
    moderate = share_desire_weight(ShareDesire.moderate)
    eager = share_desire_weight(ShareDesire.eager)
    assert mild == 0.15
    assert moderate == 0.35
    assert eager == 0.65
    assert PROACTIVE_OPEN_THRESHOLD == 0.65
    assert REPLY_URGE_THRESHOLD == 0.35
    # 最少条数（仅 toward_user，无其它来源）
    assert mild * 5 >= PROACTIVE_OPEN_THRESHOLD  # 5 mild
    assert moderate * 2 >= PROACTIVE_OPEN_THRESHOLD  # 2 moderate
    assert eager * 1 >= PROACTIVE_OPEN_THRESHOLD  # 1 eager


def test_lower_proactive_threshold_would_fire_single_moderate():
    """若 proactive_open 降到 0.35，单条 moderate 即可 scan 触发。"""
    exp = ExpectationState()
    interaction = PresenceInteraction()
    apply_non_dialogue_share_refresh(
        exp,
        interaction,
        {
            "wants_to_share": "true",
            "share_topic": "今天有个想法",
            "share_desire": "moderate",
        },
        source="life:experience",
    )
    scan = scan_expectation_thresholds(
        session_id="tao",
        expectation=exp,
        interaction=interaction,
        line_open=False,
        proactive_threshold=0.35,
    )
    assert scan.triggered is True
    assert scan.mode == ExpectationScanMode.proactive_open
