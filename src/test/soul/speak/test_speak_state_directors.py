from __future__ import annotations

from agent.soul.speak.responders.request_driven.directors.fallback import fallback_delivery_plan
from agent.soul.speak.responders.request_driven.orchestrator.state.core.delivery import ReplySegment, build_delivery_plan
from agent.soul.speak.responders.request_driven.orchestrator.state.core.enums import normalize_continuity
from agent.soul.speak.responders.request_driven.orchestrator.state.core.types import (
    DialogueSnapshot,
    SessionRuntimeSnapshot,
    SessionSignals,
    SessionSnapshot,
    build_snapshot_id,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import StateStore
from agent.soul.speak.responders.request_driven.orchestrator.state.snapshot.print import print_session_snapshot


def _snapshot(user_text: str = "今天天气不错") -> SessionSnapshot:
    signals = SessionSignals(session_id="tao", turn_index=1, generation=0)
    return SessionSnapshot(
        schema_version=1,
        snapshot_id=build_snapshot_id("tao", turn_index=1, generation=0),
        session_id="tao",
        signals=signals,
        runtime=SessionRuntimeSnapshot(),
        dialogue=DialogueSnapshot(user_text=user_text),
    )


def test_director_voice_guides_character_without_lines():
    from agent.soul.speak.responders.request_driven.directors.base import DIRECTOR_VOICE
    from agent.soul.speak.responders.request_driven.directors.rhythm_schedule import (
        _ENRICH_RULE,
    )
    from agent.soul.speak.responders.request_driven.directors.turn_delivery import (
        TurnDeliveryDirector,
    )

    assert "你在指导角色" in DIRECTOR_VOICE
    assert "连续过程" in DIRECTOR_VOICE
    assert "绝不写角色台词" in DIRECTOR_VOICE
    assert "角色 agent 管控" in DIRECTOR_VOICE
    assert "不用第一人称「我」去演角色" in DIRECTOR_VOICE
    assert "只写 <speak>" in DIRECTOR_VOICE
    assert "虚空产粮" in DIRECTOR_VOICE
    assert "不要写角色台词" in _ENRICH_RULE
    assert "动作必须写全在这张卡里" in _ENRICH_RULE
    assert "sample_narration 只写这一拍的连续过程" in TurnDeliveryDirector._SYSTEM
    assert "不要用「我」扮演角色" in TurnDeliveryDirector._SYSTEM
    assert "角色只会发一条短消息" in TurnDeliveryDirector._SYSTEM


def test_normalize_continuity_unknown_maps_finish():
    assert normalize_continuity("weird") == "finish"


def test_delivery_plan_builder():
    plan = build_delivery_plan(
        segments=[
            ReplySegment(text="是啊", wait_ms=0, continuity="finish"),
            ReplySegment(text="唉", wait_ms=300, wait_reason="停顿", continuity="append"),
        ],
        continuity="append",
        sample_narration="sample",
    )
    assert len(plan.segments) == 2
    assert plan.continuity == "append"


def test_fallback_delivery_plan_produces_segment():
    plan = fallback_delivery_plan(_snapshot(), user_text="你好")
    assert not plan.is_empty
    assert plan.segments[0].wait_ms >= 120


def test_state_store_delivery_plan_roundtrip():
    store = StateStore()
    plan = build_delivery_plan(
        segments=[ReplySegment(text="嗯", wait_ms=120, continuity="finish")],
    )
    store.set_delivery_plan("tao", plan, pending=True)
    taken = store.take_pending_delivery_plan("tao")
    assert taken is not None
    assert taken.segments[0].text == "嗯"


def test_print_session_snapshot_contains_delivery_sample():
    store = StateStore()
    plan = build_delivery_plan(
        segments=[ReplySegment(text="是啊", wait_ms=0)],
        sample_narration="user: hi\nagent: 是啊[立刻回复]",
    )
    store.set_delivery_plan("tao", plan)
    text = print_session_snapshot(_snapshot(), state_store=store)
    assert "delivery_sample" in text
    assert "是啊" in text
