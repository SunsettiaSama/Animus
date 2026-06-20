from __future__ import annotations

from agent.soul.speak.orchestrator.directors.fallback import fallback_delivery_plan
from agent.soul.speak.orchestrator.state.core.delivery import ReplySegment, build_delivery_plan
from agent.soul.speak.orchestrator.state.core.enums import normalize_continuity
from agent.soul.speak.orchestrator.state.core.types import (
    DialogueSnapshot,
    SessionRuntimeSnapshot,
    SessionSignals,
    SessionSnapshot,
    build_snapshot_id,
)
from agent.soul.speak.orchestrator.state.runtime.store import StateStore
from agent.soul.speak.orchestrator.state.snapshot.print import print_session_snapshot


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
