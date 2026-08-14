"""Worker portraits consume units; Soul persona stays out of Worker system path."""
from __future__ import annotations

from worker.context import ContextTimeline
from worker.state.memory_distill.source import gather_portrait_source
from worker.state.schema import AgentStateSnapshot
from worker.state.work_reflection.reflection import ReflectionTurn


def test_gather_portrait_source_includes_worker_units():
    bundle = gather_portrait_source(
        memory=None,
        worker_unit_lines=["user: 修 bug", "act: command_lookup", "obs: powershell_run"],
    )
    assert not bundle.is_empty
    assert bundle.worker_unit_lines
    assert "work:" in bundle.source_revision


def test_reflection_turn_prefers_units_in_revision():
    turn_a = ReflectionTurn(
        question="q",
        answer="a",
        steps=({"action": "x", "observation": "o"},),
        task_graph="g",
        units=(),
    )
    turn_b = ReflectionTurn(
        question="q",
        answer="a",
        steps=({"action": "x", "observation": "o"},),
        task_graph="g",
        units=({"kind": "user", "payload": {"text": "hi"}},),
    )
    assert turn_a.revision() != turn_b.revision()


def test_worker_snapshot_text_is_self_contained():
    snap = AgentStateSnapshot.from_slots()
    assert snap.worker_portrait_text()
    assert snap.reflection_portrait_text()
    # Memory portrait may be empty initially.
    assert isinstance(snap.memory_portrait_text(), str)


def test_timeline_summary_feeds_distill():
    tl = ContextTimeline()
    tl.add_user("实现注入")
    ta = tl.add_thought_action(
        thought="查命令",
        action="command_lookup",
        action_input={"query": "dir"},
        step_index=0,
    )
    tl.add_observation("run_tool=cmd_run", parent_id=ta.unit_id, tool="command_lookup")
    lines = tl.summary_lines()
    assert any(line.startswith("user:") for line in lines)
    assert any("command_lookup" in line for line in lines)
