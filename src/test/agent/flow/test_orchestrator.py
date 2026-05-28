"""Tests for agent.flow.orchestrator with a mock ExecutorAgent."""

from __future__ import annotations



import asyncio

import sys

from pathlib import Path

from unittest.mock import AsyncMock, MagicMock, patch



SRC = Path(__file__).resolve().parent.parent.parent

if str(SRC) not in sys.path:

    sys.path.insert(0, str(SRC))



import pytest

from agent.base import AgentResult

from agent.flow.cluster.config import LogConfig, OrchestratorConfig, PlannerConfig, ReplannerConfig

from agent.flow.cluster.document import PlanDocument, PlanParser, TaskStatus

from agent.flow.cluster.orchestrator import FlowOrchestrator





_SIMPLE_MD = """

# Plan: Orchestrator Test



## Objective

Test orchestration with mock executor.



## Tasks



### Module: core

- [ ] **step_one** `profile:minimal`

  Do step one.

- [ ] **step_two** `profile:minimal` `depends_on:step_one`

  Do step two.

"""



_PARALLEL_MD = """

# Plan: Parallel Test



## Objective

Test parallel execution.



## Tasks



### Module: core

- [ ] **task_a** `profile:minimal`

  Task A.

- [ ] **task_b** `profile:minimal`

  Task B (runs in parallel with A).

- [ ] **task_c** `profile:minimal` `depends_on:task_a,task_b`

  Task C (waits for both).

"""



_WRITES_MD = """

# Plan: Resource Lock Test



## Objective

Test write resource locking.



## Tasks



### Module: core

- [ ] **writer_a** `profile:minimal` `writes:shared.txt`

  Write to shared file.

- [ ] **writer_b** `profile:minimal` `writes:shared.txt`

  Also writes to shared file ï¿?should not run concurrently.

"""





def _make_executor_mock(result_fn=None):

    """Returns a mock ExecutorAgent.run that simulates success."""

    async def _run(instruction, **ctx):

        task = ctx.get("task")

        doc = ctx.get("doc")

        if task and doc:

            from agent.flow.cluster.document import TaskExecutionContext

            ctx_obj = TaskExecutionContext(

                task_id=task.task_id, status="done",

                result_summary="ok", step_count=1,

            )

            await doc.update_task(task.task_id, status=TaskStatus.done, result="ok", execution_ctx=ctx_obj)

        return AgentResult(agent_id="mock", role="executor", status="done", output="ok")



    mock = MagicMock()

    mock.run = AsyncMock(side_effect=result_fn or _run)

    return mock





def _make_orch(tmp_path):

    cfg = OrchestratorConfig(

        plan_dir=str(tmp_path),

        planner=PlannerConfig(),

        replanner=ReplannerConfig(triggers=[]),

        log=LogConfig(enabled=False),

        parallel_limit=4,

        human_edit=False,

        snapshot_triggers=[],

    )

    return FlowOrchestrator(cfg=cfg, llm_cfg_path="")


def _bind_dispatch_ctx(orch, doc):
    from agent.flow.cluster.execution_context import PlanExecutionContext

    orch._ctx = PlanExecutionContext.from_config(doc.plan_id, orch._cfg.parallel_limit, doc)





class TestFlowOrchestratorDispatch:

    def test_sequential_execution(self, tmp_path):

        orch = _make_orch(tmp_path)

        doc = PlanParser.parse(_SIMPLE_MD)

        doc.plan_id = "test-seq"



        orch._executor_agent = _make_executor_mock()



        from agent.flow.cluster.log import PlanLogger

        from agent.flow.cluster.snapshot import SnapshotStore

        from agent.flow.cluster.channel import HumanEditChannel

        logger = PlanLogger(str(tmp_path), doc.plan_id, LogConfig(enabled=False))

        snapshots = SnapshotStore(str(tmp_path), doc.plan_id)

        channel = HumanEditChannel(str(tmp_path), doc.plan_id)

        _bind_dispatch_ctx(orch, doc)

        asyncio.get_event_loop().run_until_complete(

            orch._dispatch_all(doc, snapshots, channel, logger, doc.plan_id, asyncio.Lock())

        )



        assert doc.get_task("step_one").status == TaskStatus.done

        assert doc.get_task("step_two").status == TaskStatus.done



    def test_parallel_execution(self, tmp_path):

        orch = _make_orch(tmp_path)

        doc = PlanParser.parse(_PARALLEL_MD)

        doc.plan_id = "test-par"



        execution_order = []



        async def _run_with_log(instruction, **ctx):

            task = ctx.get("task")

            doc_ = ctx.get("doc")

            if task:

                execution_order.append(task.task_id)

                from agent.flow.cluster.document import TaskExecutionContext

                ec = TaskExecutionContext(task_id=task.task_id, status="done", result_summary="ok", step_count=1)

                await doc_.update_task(task.task_id, status=TaskStatus.done, result="ok", execution_ctx=ec)

            return AgentResult(agent_id="mock", role="executor", status="done", output="ok")



        orch._executor_agent = _make_executor_mock(_run_with_log)



        from agent.flow.cluster.log import PlanLogger

        from agent.flow.cluster.snapshot import SnapshotStore

        from agent.flow.cluster.channel import HumanEditChannel

        logger = PlanLogger(str(tmp_path), doc.plan_id, LogConfig(enabled=False))

        snapshots = SnapshotStore(str(tmp_path), doc.plan_id)

        channel = HumanEditChannel(str(tmp_path), doc.plan_id)

        _bind_dispatch_ctx(orch, doc)

        asyncio.get_event_loop().run_until_complete(

            orch._dispatch_all(doc, snapshots, channel, logger, doc.plan_id, asyncio.Lock())

        )



        for t in doc.all_tasks():

            assert t.status == TaskStatus.done



        # task_c must come after both task_a and task_b

        assert execution_order.index("task_c") > execution_order.index("task_a")

        assert execution_order.index("task_c") > execution_order.index("task_b")



    def test_writes_resource_guard(self, tmp_path):

        """Two tasks writing to the same file should not run concurrently."""

        orch = _make_orch(tmp_path)

        doc = PlanParser.parse(_WRITES_MD)

        doc.plan_id = "test-writes"



        timestamps = {}

        import time



        async def _run_timed(instruction, **ctx):

            task = ctx.get("task")

            doc_ = ctx.get("doc")

            if task:

                timestamps[task.task_id] = time.monotonic()

                await asyncio.sleep(0.05)  # Simulate work

                from agent.flow.cluster.document import TaskExecutionContext

                ec = TaskExecutionContext(task_id=task.task_id, status="done", result_summary="ok", step_count=1)

                await doc_.update_task(task.task_id, status=TaskStatus.done, result="ok", execution_ctx=ec)

            return AgentResult(agent_id="mock", role="executor", status="done", output="ok")



        orch._executor_agent = _make_executor_mock(_run_timed)



        from agent.flow.cluster.log import PlanLogger

        from agent.flow.cluster.snapshot import SnapshotStore

        from agent.flow.cluster.channel import HumanEditChannel

        logger = PlanLogger(str(tmp_path), doc.plan_id, LogConfig(enabled=False))

        snapshots = SnapshotStore(str(tmp_path), doc.plan_id)

        channel = HumanEditChannel(str(tmp_path), doc.plan_id)

        _bind_dispatch_ctx(orch, doc)

        asyncio.get_event_loop().run_until_complete(

            orch._dispatch_all(doc, snapshots, channel, logger, doc.plan_id, asyncio.Lock())

        )



        # Both tasks should complete

        assert doc.get_task("writer_a").status == TaskStatus.done

        assert doc.get_task("writer_b").status == TaskStatus.done



        # Because they write to the same file, they must not start at the same time

        # (one should start after the other finishes its sleep of 0.05s)

        t_a = timestamps.get("writer_a", 0)

        t_b = timestamps.get("writer_b", 0)

        assert abs(t_a - t_b) >= 0.04, "Resource-guarded tasks should not overlap"



    def test_emits_events(self, tmp_path):

        orch = _make_orch(tmp_path)

        doc = PlanParser.parse(_SIMPLE_MD)

        doc.plan_id = "test-events"

        orch._executor_agent = _make_executor_mock()



        emitted = []

        orch.subscribe(lambda e: emitted.append(type(e).__name__))



        from agent.flow.cluster.log import PlanLogger

        from agent.flow.cluster.snapshot import SnapshotStore

        from agent.flow.cluster.channel import HumanEditChannel

        logger = PlanLogger(str(tmp_path), doc.plan_id, LogConfig(enabled=False))

        snapshots = SnapshotStore(str(tmp_path), doc.plan_id)

        channel = HumanEditChannel(str(tmp_path), doc.plan_id)

        _bind_dispatch_ctx(orch, doc)

        asyncio.get_event_loop().run_until_complete(

            orch._dispatch_all(doc, snapshots, channel, logger, doc.plan_id, asyncio.Lock())

        )



        assert "TaskStartEvent" in emitted

        assert "TaskRunningEvent" in emitted

        assert "TaskCompleteEvent" in emitted

