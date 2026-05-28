from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_spec = importlib.util.spec_from_file_location(
    "agent.soul.speak.session.queue.memory",
    SRC / "agent/soul/speak/session/queue/memory.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["agent.soul.speak.session.queue.memory"] = _mod
_spec.loader.exec_module(_mod)

MemoryQueueItem = _mod.MemoryQueueItem
SessionMemoryQueue = _mod.SessionMemoryQueue


def test_memory_queue_injects_near_turn_and_spills_stale():
    queue = SessionMemoryQueue(max_turn_gap=3)
    queue.enqueue(
        "s1",
        MemoryQueueItem(turn_index=1, lines=("old",), unit_ids=("u-old",)),
    )
    queue.enqueue(
        "s1",
        MemoryQueueItem(turn_index=4, lines=("near",), unit_ids=("u-near",)),
    )

    result = queue.consume_for_compose("s1", current_turn_index=5)

    assert result.spilled_lines == ["old"]
    assert result.spilled_unit_ids == ["u-old"]
    assert result.spilled_turn_index == 1
    assert result.inject_lines == ["near"]
    assert result.inject_unit_ids == ["u-near"]
    assert result.inject_turn_index == 4


def test_session_registry_begin_turn_increments():
    lifecycle_types = types.ModuleType("agent.soul.speak.session.lifecycle.types")
    lifecycle_types.SessionEndReason = str
    lifecycle_types.SessionEndResult = object
    lifecycle_types.SessionLifecyclePort = object
    sys.modules["agent.soul.speak.session.lifecycle.types"] = lifecycle_types

    init_mod = types.ModuleType("agent.soul.speak.session.lifecycle.init.bootstrap")
    sys.modules["agent.soul.speak.session.lifecycle.init.bootstrap"] = init_mod

    hold_pkg = types.ModuleType("agent.soul.speak.session.lifecycle.hold")
    hold_pkg.__path__ = [str(SRC / "agent/soul/speak/session/lifecycle/hold")]
    sys.modules["agent.soul.speak.session.lifecycle.hold"] = hold_pkg

    registry_spec = importlib.util.spec_from_file_location(
        "agent.soul.speak.session.lifecycle.hold.registry",
        SRC / "agent/soul/speak/session/lifecycle/hold/registry.py",
    )
    registry_mod = importlib.util.module_from_spec(registry_spec)
    sys.modules["agent.soul.speak.session.lifecycle.hold.registry"] = registry_mod
    registry_spec.loader.exec_module(registry_mod)

    registry = registry_mod.SpeakSessionRegistry()
    first = registry.begin_turn("s1")
    second = registry.begin_turn("s1")
    assert first == 1
    assert second == 2
    assert registry.current_turn_index("s1") == 2
