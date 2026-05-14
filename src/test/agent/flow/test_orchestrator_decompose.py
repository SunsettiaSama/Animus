"""Integration tests for the atomic planning layer inside FlowOrchestrator.

Tests use mock AtomicPlanner and mock ExecutorAgent — no LLM calls.
Follows the same async execution pattern as test_orchestrator.py.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from agent.base import AgentResult
from agent.flow.base.budget import DecompositionBudget, TopologyKind
from agent.flow.base.components.node_spec import NodeManifest, TopologyDecision
from agent.flow.channel import HumanEditChannel
from agent.flow.config import LogConfig, OrchestratorConfig, PlannerConfig, ReplannerConfig
from agent.flow.document import PlanDocument, PlanParser, TaskStatus
from agent.flow.execution_context import PlanExecutionContext
from agent.flow.log import PlanLogger
from agent.flow.orchestrator import FlowOrchestrator
from agent.flow.snapshot import SnapshotStore


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_cfg(tmp_path, max_depth: int = 3) -> OrchestratorConfig:
    return OrchestratorConfig(
        plan_dir=str(tmp_path),
        planner=PlannerConfig(),
        replanner=ReplannerConfig(triggers=[]),
        log=LogConfig(enabled=False),
        parallel_limit=4,
        human_edit=False,
        snapshot_triggers=[],
        decomposition=DecompositionBudget(max_depth=max_depth, max_width=8, max_atom_steps=5),
    )


def _make_orch(tmp_path, max_depth: int = 3) -> FlowOrchestrator:
    return FlowOrchestrator(cfg=_make_cfg(tmp_path, max_depth), llm_cfg_path="")


def _bind_ctx(orch: FlowOrchestrator, doc: PlanDocument) -> None:
    orch._ctx = PlanExecutionContext.from_config(doc.plan_id, orch._cfg.parallel_limit, doc)


def _make_infra(tmp_path, plan_id: str):
    logger    = PlanLogger(str(tmp_path), plan_id, LogConfig(enabled=False))
    snapshots = SnapshotStore(str(tmp_path), plan_id)
    channel   = HumanEditChannel(str(tmp_path), plan_id)
    return logger, snapshots, channel


def _make_executor_mock():
    async def _run(instruction, **ctx):
        task = ctx.get("task")
        doc  = ctx.get("doc")
        if task and doc:
            from agent.flow.document import TaskExecutionContext
            result = f"result_of_{task.task_id}"
            ec = TaskExecutionContext(task_id=task.task_id, status="done",
                                      result_summary=result, step_count=1)
            await doc.update_task(task.task_id, status=TaskStatus.done,
                                  result=result, execution_ctx=ec)
        return AgentResult(
            agent_id="mock", role="executor", status="done",
            output=f"result_of_{ctx['task'].task_id}" if ctx.get("task") else "ok",
        )

    m = MagicMock()
    m.run = AsyncMock(side_effect=_run)
    return m


def _run_dispatch(orch, doc, tmp_path):
    plan_id = doc.plan_id
    _bind_ctx(orch, doc)
    logger, snapshots, channel = _make_infra(tmp_path, plan_id)
    asyncio.get_event_loop().run_until_complete(
        orch._dispatch_all(doc, snapshots, channel, logger, plan_id, asyncio.Lock())
    )


def _simple_doc() -> PlanDocument:
    doc = PlanParser.parse("""# Plan: Simple Test
## Objective
Two sequential tasks.
## Tasks
### Module: core
- [ ] **task_a** `profile:minimal`
  Do task A.
- [ ] **task_b** `profile:minimal` `depends_on:task_a`
  Do task B.
""")
    doc.plan_id = "simple-test"
    return doc


def _single_task_doc(task_id: str = "complex_task") -> PlanDocument:
    doc = PlanParser.parse(f"""# Plan: Decompose Test
## Objective
Test decomposition.
## Tasks
### Module: core
- [ ] **{task_id}** `profile:minimal`
  Build the entire authentication module including login and registration.
""")
    doc.plan_id = f"decompose-{task_id}"
    return doc


# ── Mock AtomicPlanner helpers ────────────────────────────────────────────────

def _mock_planner(decision_fn):
    """Returns mock AtomicPlanner whose assess(manifest, budget) → decision_fn(manifest, budget)."""
    planner = MagicMock()
    async def _assess(manifest, budget, *, context=None):
        return decision_fn(manifest, budget)
    planner.assess = AsyncMock(side_effect=_assess)
    return planner


def _always_atomic(manifest, budget):
    return TopologyDecision(kind=TopologyKind.atomic, reason="mock atomic")


def _flat_two_subs(manifest, budget):
    return TopologyDecision(
        kind=TopologyKind.flat,
        reason="mock flat: two sequential sub-tasks",
        output_node_id="sub_b",
        sub_manifests=(
            NodeManifest(task_id="sub_a", description="Sub task A",
                         input_contract="in", output_contract="mid"),
            NodeManifest(task_id="sub_b", description="Sub task B",
                         depends_on=("sub_a",), input_contract="mid", output_contract="out"),
        ),
    )


def _nested_two_inner(manifest, budget):
    return TopologyDecision(
        kind=TopologyKind.nested,
        reason="mock nested: private sub-graph",
        output_node_id="inner_exit",
        sub_manifests=(
            NodeManifest(task_id="inner_entry", description="Inner entry",
                         input_contract="in", output_contract="mid"),
            NodeManifest(task_id="inner_exit", description="Inner exit",
                         depends_on=("inner_entry",), input_contract="mid",
                         output_contract="out"),
        ),
    )


# ── Tests: atomic passthrough ─────────────────────────────────────────────────

class TestAtomicPassthrough:

    def test_atomic_executes_tasks_normally(self, tmp_path):
        """With atomic decisions, all tasks run via ExecutorAgent as-is."""
        doc = _simple_doc()
        orch = _make_orch(tmp_path)
        orch._atomic_planner = _mock_planner(_always_atomic)
        orch._executor_agent = _make_executor_mock()

        _run_dispatch(orch, doc, tmp_path)

        assert doc.get_task("task_a").status == TaskStatus.done
        assert doc.get_task("task_b").status == TaskStatus.done
        assert orch._executor_agent.run.call_count == 2

    def test_atomic_result_from_executor(self, tmp_path):
        doc = _simple_doc()
        orch = _make_orch(tmp_path)
        orch._atomic_planner = _mock_planner(_always_atomic)
        orch._executor_agent = _make_executor_mock()

        _run_dispatch(orch, doc, tmp_path)

        assert doc.get_task("task_a").result == "result_of_task_a"
        assert doc.get_task("task_b").result == "result_of_task_b"


# ── Tests: flat expansion ─────────────────────────────────────────────────────

class TestFlatExpansion:

    def test_flat_replaces_task_with_subtasks(self, tmp_path):
        """Flat decision: original task ends as done; sub-tasks ran via executor."""
        doc = _single_task_doc("complex_task")
        orch = _make_orch(tmp_path)

        executed: list[str] = []

        def _flat_once(manifest, budget):
            if manifest.task_id == "complex_task":
                return _flat_two_subs(manifest, budget)
            return _always_atomic(manifest, budget)

        async def _exec_run(instruction, **ctx):
            task = ctx.get("task"); d = ctx.get("doc")
            if task and d:
                from agent.flow.document import TaskExecutionContext
                executed.append(task.task_id)
                result = f"result_of_{task.task_id}"
                ec = TaskExecutionContext(task_id=task.task_id, status="done",
                                          result_summary=result, step_count=1)
                await d.update_task(task.task_id, status=TaskStatus.done,
                                    result=result, execution_ctx=ec)
            return AgentResult(agent_id="m", role="executor", status="done",
                               output=f"result_of_{ctx['task'].task_id}" if ctx.get("task") else "ok")

        orch._atomic_planner = _mock_planner(_flat_once)
        orch._executor_agent = MagicMock()
        orch._executor_agent.run = AsyncMock(side_effect=_exec_run)

        _run_dispatch(orch, doc, tmp_path)

        assert doc.get_task("complex_task").status == TaskStatus.done
        assert "sub_a" in executed
        assert "sub_b" in executed
        # exit-node result propagates up
        assert doc.get_task("complex_task").result == "result_of_sub_b"

    def test_flat_dependency_order_respected(self, tmp_path):
        """sub_b depends_on sub_a → execution order is sub_a then sub_b."""
        doc = _single_task_doc("big_task")
        orch = _make_orch(tmp_path)

        order: list[str] = []

        def _flat_once(manifest, budget):
            if manifest.task_id == "big_task":
                return _flat_two_subs(manifest, budget)
            return _always_atomic(manifest, budget)

        async def _exec_run(instruction, **ctx):
            task = ctx.get("task"); d = ctx.get("doc")
            if task and d:
                from agent.flow.document import TaskExecutionContext
                order.append(task.task_id)
                result = f"r_{task.task_id}"
                ec = TaskExecutionContext(task_id=task.task_id, status="done",
                                          result_summary=result, step_count=1)
                await d.update_task(task.task_id, status=TaskStatus.done,
                                    result=result, execution_ctx=ec)
            return AgentResult(agent_id="m", role="executor", status="done", output="ok")

        orch._atomic_planner = _mock_planner(_flat_once)
        orch._executor_agent = MagicMock()
        orch._executor_agent.run = AsyncMock(side_effect=_exec_run)

        _run_dispatch(orch, doc, tmp_path)

        assert order.index("sub_a") < order.index("sub_b")


# ── Tests: nested execution ───────────────────────────────────────────────────

class TestNestedExecution:

    def test_nested_runs_inner_graph(self, tmp_path):
        """Nested decision: both inner nodes run; exit-node result propagates up."""
        doc = _single_task_doc("auth_module")
        orch = _make_orch(tmp_path)

        def _nested_once(manifest, budget):
            if manifest.task_id == "auth_module":
                return _nested_two_inner(manifest, budget)
            return _always_atomic(manifest, budget)

        orch._atomic_planner = _mock_planner(_nested_once)
        orch._executor_agent = _make_executor_mock()

        _run_dispatch(orch, doc, tmp_path)

        parent = doc.get_task("auth_module")
        assert parent.status == TaskStatus.done
        assert parent.result == "result_of_inner_exit"

    def test_nested_inner_dependency_order(self, tmp_path):
        """inner_entry must complete before inner_exit in nested sub-graph."""
        doc = _single_task_doc("guarded_task")
        orch = _make_orch(tmp_path)

        order: list[str] = []

        def _nested_once(manifest, budget):
            if manifest.task_id == "guarded_task":
                return _nested_two_inner(manifest, budget)
            return _always_atomic(manifest, budget)

        async def _exec_run(instruction, **ctx):
            task = ctx.get("task"); d = ctx.get("doc")
            if task and d:
                from agent.flow.document import TaskExecutionContext
                order.append(task.task_id)
                result = f"result_of_{task.task_id}"
                ec = TaskExecutionContext(task_id=task.task_id, status="done",
                                          result_summary=result, step_count=1)
                await d.update_task(task.task_id, status=TaskStatus.done,
                                    result=result, execution_ctx=ec)
            return AgentResult(agent_id="m", role="executor", status="done",
                               output=f"result_of_{ctx['task'].task_id}" if ctx.get("task") else "ok")

        orch._atomic_planner = _mock_planner(_nested_once)
        orch._executor_agent = MagicMock()
        orch._executor_agent.run = AsyncMock(side_effect=_exec_run)

        _run_dispatch(orch, doc, tmp_path)

        assert order.index("inner_entry") < order.index("inner_exit")


# ── Tests: budget enforcement ─────────────────────────────────────────────────

class TestBudgetEnforcement:

    def test_no_decomposition_when_depth_zero(self, tmp_path):
        """max_depth=0: _atomic_planner is None, tasks execute directly."""
        doc = _simple_doc()
        orch = _make_orch(tmp_path, max_depth=0)

        # With max_depth=0, _build_agents should not set up an atomic planner.
        # Force None to verify the path.
        assert orch._atomic_planner is None
        orch._executor_agent = _make_executor_mock()

        _run_dispatch(orch, doc, tmp_path)

        assert all(t.status == TaskStatus.done for t in doc.all_tasks())
        assert orch._executor_agent.run.call_count == 2

    def test_nested_passes_descend_budget(self, tmp_path):
        """Nested call receives budget.descend() — depth is one less."""
        doc = _single_task_doc("outer_task")
        orch = _make_orch(tmp_path, max_depth=2)

        received_budgets: list[DecompositionBudget] = []

        async def _assess(manifest, budget, *, context=None):
            received_budgets.append(budget)
            if manifest.task_id == "outer_task":
                return _nested_two_inner(manifest, budget)
            return TopologyDecision(kind=TopologyKind.atomic, reason="inner atomic")

        mock_ap = MagicMock()
        mock_ap.assess = AsyncMock(side_effect=_assess)
        orch._atomic_planner = mock_ap
        orch._executor_agent = _make_executor_mock()

        _run_dispatch(orch, doc, tmp_path)

        outer_budgets = [b for b in received_budgets if b.max_depth == 2]
        inner_budgets = [b for b in received_budgets if b.max_depth == 1]
        assert len(outer_budgets) >= 1, "outer_task should see depth=2"
        assert len(inner_budgets) >= 2, "inner nodes should see depth=1"
