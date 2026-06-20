from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

_spec = importlib.util.spec_from_file_location(
    "agent.soul.speak.orchestrator.queue.memory",
    SRC / "agent/soul/speak/orchestrator/queue/memory.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["agent.soul.speak.orchestrator.queue.memory"] = _mod
_spec.loader.exec_module(_mod)

MemoryBufferItem = _mod.MemoryBufferItem
ComposeMemoryBuffer = _mod.ComposeMemoryBuffer


def test_memory_buffer_spills_stale_emergence_and_keeps_near():
    buffer = ComposeMemoryBuffer(max_turn_gap=3)
    buffer.enqueue_turn(
        "s1",
        MemoryBufferItem(
            turn_index=1,
            lines=("old",),
            unit_ids=("u-old",),
            source="emergence",
        ),
    )
    buffer.enqueue_turn(
        "s1",
        MemoryBufferItem(
            turn_index=4,
            lines=("near",),
            unit_ids=("u-near",),
            source="emergence",
        ),
    )

    result = buffer.pull_for_compose(
        "s1",
        current_turn_index=5,
        keyword_wait_ms=0,
        budget=5,
        merge_ratio=0.0,
    )

    assert "old" not in result.inject_lines
    assert "u-old" not in result.inject_unit_ids
    assert "near" in result.inject_lines
    assert "u-near" in result.inject_unit_ids


def test_memory_buffer_keyword_only_for_current_turn():
    buffer = ComposeMemoryBuffer(max_turn_gap=3)
    buffer.enqueue_turn(
        "s1",
        MemoryBufferItem(
            turn_index=1,
            lines=("kw-old",),
            unit_ids=("u-kw-old",),
            source="keyword",
        ),
    )
    buffer.enqueue_turn(
        "s1",
        MemoryBufferItem(
            turn_index=2,
            lines=("kw-now",),
            unit_ids=("u-kw-now",),
            source="keyword",
        ),
    )

    result = buffer.pull_for_compose(
        "s1",
        current_turn_index=2,
        keyword_wait_ms=0,
        budget=5,
        merge_ratio=1.0,
    )

    assert result.inject_lines == ["kw-now"]
    assert result.inject_unit_ids == ["u-kw-now"]
