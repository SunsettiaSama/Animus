from __future__ import annotations

import threading
from unittest.mock import MagicMock

from agent.soul.speak.responders.request_driven.orchestrator.runtime.orchestrator_thread import (
    OrchestratorThread,
)
from agent.soul.speak.responders.request_driven.orchestrator.state import StateStore
from agent.soul.speak.service import SpeakService
from agent.soul.speak.session.manage.enter_greeting import EnterGreetingManager
from agent.soul.speak.session.manage.silence_break import SilenceBreakManager
from agent.soul.speak.session.queue import SessionQueueHub
from agent.soul.workers import DomainWorker
from infra.threading import ThreadRegistry, get_thread_registry


def setup_function() -> None:
    ThreadRegistry.reset()


def teardown_function() -> None:
    ThreadRegistry.reset()


def test_orchestrator_poll_thread_registered_under_speak_owner():
    store = StateStore()
    thread = OrchestratorThread(state_store=store)
    registry = get_thread_registry()
    thread.start()
    names = {item["name"] for item in registry.status("speak")}
    assert "speak-orchestrator-thread" in names
    assert "speak-orchestrator-poll" in names
    thread.stop()
    assert registry.leases_for("speak") == []


def test_orchestrator_delivery_ready_does_not_promote_director_plan():
    store = MagicMock()
    plan = MagicMock()
    plan.is_empty = False
    store.take_pending_delivery_plan.return_value = plan
    ready: list[tuple[str, str]] = []
    thread = OrchestratorThread(
        state_store=store,
        on_delivery_ready=lambda session_id, trigger: ready.append(
            (session_id, trigger),
        ),
    )

    thread._maybe_notify_delivery("s1", trigger="idle")

    store.set_delivery_plan.assert_not_called()
    assert ready == []


def test_async_delivery_does_not_push_director_plan():
    service = object.__new__(SpeakService)
    plan = MagicMock()
    plan.is_empty = False
    state = MagicMock()
    state.speak_gate = "speak"
    state.delivery_plan = plan
    service._state_store = MagicMock()
    service._state_store.session.return_value = state
    service._delivery_executor = MagicMock()
    service._session_manager = MagicMock()
    service._outbound_stream = MagicMock()
    service._outbound_stream.port.has_connection = None
    service._outbound_stream.port.is_client_turn_active = None

    service._execute_async_delivery_for_session("s1")

    service._delivery_executor.execute.assert_not_called()


def test_async_delivery_waits_for_live_idle_route():
    service = object.__new__(SpeakService)
    state = MagicMock()
    state.speak_gate = "speak"
    state.delivery_plan = MagicMock(is_empty=False)
    service._state_store = MagicMock()
    service._state_store.session.return_value = state
    service._delivery_executor = MagicMock()
    service._session_manager = MagicMock()
    service._outbound_stream = MagicMock()
    service._outbound_stream.port.has_connection.return_value = False

    service._execute_async_delivery_for_session("s1")

    service._delivery_executor.execute.assert_not_called()


def test_async_delivery_waits_until_client_turn_finishes():
    service = object.__new__(SpeakService)
    state = MagicMock()
    state.speak_gate = "speak"
    state.delivery_plan = MagicMock(is_empty=False)
    service._state_store = MagicMock()
    service._state_store.session.return_value = state
    service._delivery_executor = MagicMock()
    service._session_manager = MagicMock()
    service._outbound_stream = MagicMock()
    service._outbound_stream.port.has_connection.return_value = True
    service._outbound_stream.port.is_client_turn_active.return_value = True

    service._execute_async_delivery_for_session("s1")

    service._delivery_executor.execute.assert_not_called()


def test_speak_owner_stop_after_worker_start_clears_leases():
    """SpeakService.stop 的最终兜底：owner=speak 的租约应被收束。"""
    registry = get_thread_registry()
    worker = DomainWorker("speak-compose-worker", owner="speak")
    worker.start()
    assert registry.leases_for("speak")
    still = registry.stop_owner("speak", timeout=2.0)
    assert still == []
    assert registry.leases_for("speak") == []


def test_webui_turn_lease_request_pattern():
    """WebUI turn 线程：request -> start -> stop/join 后注销。"""
    registry = get_thread_registry()
    done = threading.Event()

    def _run_turn() -> None:
        done.set()

    lease = registry.request("speak", "webui-speak-turn", _run_turn, daemon=True)
    lease.start()
    assert done.wait(timeout=2.0)
    assert lease.stop(timeout=2.0) is True
    assert registry.leases_for("speak") == []


def test_enter_greeting_and_silence_stop_cancel_session_timers():
    registry_mock = MagicMock()
    record = MagicMock()
    record.generation = 1
    registry_mock.get.return_value = record
    greeting = EnterGreetingManager(registry=registry_mock)
    silence = SilenceBreakManager(registry=registry_mock)

    greeting.arm_session("s1")
    assert "s1" in greeting._states
    assert greeting._states["s1"].timer is not None
    greeting.stop_worker()
    assert greeting._states == {}

    silence.on_agent_turn_complete("s2")
    assert "s2" in silence._states
    assert silence._states["s2"].timer is not None
    silence.stop_worker()
    assert silence._states == {}


def test_session_queue_hub_cancel_all_timers():
    hub = SessionQueueHub()
    runtime = hub._runtime("s1")
    with runtime.lock:
        runtime.idle_timer = threading.Timer(60.0, lambda: None)
        runtime.idle_timer.daemon = True
        runtime.idle_timer.start()
    hub.cancel_all_timers()
    with runtime.lock:
        assert runtime.idle_timer is None


def test_speak_service_stop_source_uses_infra_owner_reclaim():
    from pathlib import Path

    source = Path("src/agent/soul/speak/service.py").read_text(encoding="utf-8")
    assert "def stop(self) -> None:" in source
    assert "cancel_all_timers()" in source
    assert 'stop_owner("speak"' in source
    assert "get_thread_registry()" in source