"""ContextTimeline unit ordering, pin, and budget compression."""
from __future__ import annotations

import time

from worker.context import ContextTimeline, UnitKind, UnitPriority


def test_thought_action_and_observation_are_split():
    tl = ContextTimeline()
    tl.add_user("做这件事")
    ta = tl.add_thought_action(
        thought="先查命令",
        action="command_lookup",
        action_input={"query": "ls"},
        step_index=0,
    )
    tl.add_observation(
        "run_tool=powershell_run",
        parent_id=ta.unit_id,
        tool="command_lookup",
        source="lookup",
        step_index=0,
    )
    kinds = [u.kind for u in tl.render_order()]
    assert kinds == [UnitKind.USER, UnitKind.THOUGHT_ACTION, UnitKind.OBSERVATION]
    text = tl.render_text()
    assert "[用户输入]" in text
    assert "<T>" in text
    assert "[系统工具反馈]" in text


def test_user_interrupt_pins_ahead_of_later_observation():
    tl = ContextTimeline()
    tl.add_user("原始任务")
    ta = tl.add_thought_action(
        thought="执行中",
        action="web_search",
        action_input={"query": "x"},
        step_index=0,
    )
    # Interrupt arrives while tool would still be running.
    time.sleep(0.01)
    tl.pin_user("停一下，改目标")
    time.sleep(0.01)
    tl.add_observation(
        "search result",
        parent_id=ta.unit_id,
        tool="web_search",
        step_index=0,
    )
    ordered = tl.render_order()
    assert ordered[0].kind == UnitKind.USER
    assert ordered[0].priority == UnitPriority.HIGH
    assert "改目标" in ordered[0].payload["text"]
    # Rest keeps chronological order: original user, TA, observation.
    rest = ordered[1:]
    assert [u.kind for u in rest] == [
        UnitKind.USER,
        UnitKind.THOUGHT_ACTION,
        UnitKind.OBSERVATION,
    ]


def test_budget_compresses_old_observations():
    tl = ContextTimeline(budget_chars=1500)
    tl.add_user("goal")
    for i in range(8):
        ta = tl.add_thought_action(
            thought=f"t{i}",
            action="note_read",
            action_input={"key": "k"},
            step_index=i,
        )
        tl.add_observation(
            ("x" * 400),
            parent_id=ta.unit_id,
            tool="note_read",
            step_index=i,
        )
    assert tl.total_chars() <= 1500 + 50
    compressed = [
        u for u in tl.units
        if u.kind == UnitKind.OBSERVATION and u.metadata.get("compressed")
    ]
    assert compressed
