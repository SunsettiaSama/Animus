from __future__ import annotations

import time

from agent.soul.speak.responders.request_driven.orchestrator.runtime.ingress import (
    IngressEvent,
)
from agent.soul.speak.responders.request_driven.orchestrator.runtime.orchestrator_thread import (
    OrchestratorThread,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.delivery import (
    ReplySegment,
    build_delivery_plan,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import (
    StateStore,
)


class _FakeCoordinator:
    def __init__(self, store: StateStore) -> None:
        self._store = store
        self.calls: list[str] = []

    def on_user_input(self, session_id, user_text, *, turn_index, phase):
        self.calls.append(f"{phase}:{user_text}")
        state = self._store.session(session_id)
        if phase == "fast":
            time.sleep(0.02)
            state.speak_gate = "speak"
            state.pending_delivery_plan = build_delivery_plan(
                segments=[ReplySegment(text="…", wait_ms=50, continuity="finish")],
                continuity="finish",
                plan_id="fast-plan",
                turn_index=turn_index,
            )
            state.director_cache["ingress_phase"] = "fast"
            return {"ingress_phase": "fast"}
        if phase == "slow":
            time.sleep(0.4)
            state.director_cache["ingress_phase"] = "slow_done"
            return {"ingress_phase": "slow"}
        raise ValueError(f"unexpected phase {phase!r}")

    def take_character_handoff(self, session_id):
        return None


def test_submit_user_input_sync_only_waits_for_fast():
    store = StateStore()
    coord = _FakeCoordinator(store)
    thread = OrchestratorThread(state_store=store, coordinator=coord)
    thread.start()
    started = time.perf_counter()
    plan = thread.submit_user_input_sync(
        "s-sync",
        "信号如何",
        turn_index=2,
        timeout_sec=3.0,
    )
    elapsed = time.perf_counter() - started
    thread.stop()
    assert plan is not None
    assert not plan.is_empty
    assert elapsed < 0.3
    assert any(c.startswith("fast:") for c in coord.calls)
    assert not any(c.startswith("slow:") for c in coord.calls)


def test_ingress_event_carries_phase():
    event = IngressEvent(
        kind="user_input",
        session_id="s1",
        user_text="hi",
        turn_index=1,
        phase="fast",
    )
    assert event.phase == "fast"
