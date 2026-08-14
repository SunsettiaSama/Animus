from __future__ import annotations

import threading
import time

from infra.threading import ThreadRegistry, get_thread_registry


def setup_function() -> None:
    ThreadRegistry.reset()


def teardown_function() -> None:
    ThreadRegistry.reset()


def test_request_start_and_auto_unregister_on_finish():
    registry = get_thread_registry()
    done = threading.Event()

    def _task() -> None:
        done.set()

    lease = registry.request("speak", "speak-ephemeral", _task, daemon=True)
    lease.start()
    assert done.wait(timeout=2.0)
    deadline = time.time() + 2.0
    while lease.is_alive() and time.time() < deadline:
        time.sleep(0.01)
    assert not lease.is_alive()
    assert registry.leases_for("speak") == []


def test_stop_calls_hook_and_joins():
    registry = get_thread_registry()
    stop_flag = threading.Event()
    started = threading.Event()

    def _task() -> None:
        started.set()
        while not stop_flag.is_set():
            time.sleep(0.01)

    lease = registry.request(
        "speak",
        "speak-long",
        _task,
        daemon=True,
        stop=stop_flag.set,
    )
    lease.start()
    assert started.wait(timeout=2.0)
    assert lease.stop(timeout=2.0) is True
    assert not lease.is_alive()
    assert registry.leases_for("speak") == []


def test_stop_owner_collects_leases():
    registry = get_thread_registry()
    flags = [threading.Event(), threading.Event()]

    def _make(flag: threading.Event):
        def _task() -> None:
            while not flag.is_set():
                time.sleep(0.01)

        return _task

    lease_a = registry.request("speak", "a", _make(flags[0]), daemon=True, stop=flags[0].set)
    lease_b = registry.request("speak", "b", _make(flags[1]), daemon=True, stop=flags[1].set)
    lease_a.start()
    lease_b.start()
    assert len(registry.leases_for("speak")) == 2
    still = registry.stop_owner("speak", timeout=2.0)
    assert still == []
    assert registry.leases_for("speak") == []


def test_domain_worker_uses_thread_registry():
    from agent.soul.workers import DomainWorker

    registry = get_thread_registry()
    worker = DomainWorker("speak-test-worker", owner="speak")
    hit = threading.Event()
    worker.start()
    assert any(item["name"] == "speak-test-worker" for item in registry.status("speak"))
    worker.enqueue(hit.set)
    assert hit.wait(timeout=2.0)
    worker.stop()
    assert worker.status()["state"] == "stopped"
