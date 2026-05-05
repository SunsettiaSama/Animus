from __future__ import annotations

import asyncio
import uuid
from asyncio import Semaphore
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from plan.channel import HumanEditChannel
from plan.config import OrchestratorConfig, PlanConfig
from plan.document import PlanDocument, TaskStatus
from plan.event import (
    HumanPatchEvent,
    PlanAbortEvent,
    PlanCompleteEvent,
    PlanEvent,
    PlanStartEvent,
    ReplanEvent,
    SnapshotEvent,
    TaskCompleteEvent,
    TaskFailedEvent,
    TaskRunningEvent,
    TaskSkippedEvent,
    TaskStartEvent,
)
from plan.executor import ExecutorAgent
from plan.log import PlanLogger
from plan.patch import HumanPatch, PatchOp
from plan.planner import PlannerAgent
from plan.replanner import ReplanDecision, ReplannerAgent
from plan.result import PlanResult
from plan.snapshot import SnapshotStore


class PlanOrchestrator:
    def __init__(
        self,
        cfg: OrchestratorConfig,
        llm_cfg_path: str,
        agent_cfg: Any = None,
    ) -> None:
        self._cfg = cfg
        self._llm_cfg_path = llm_cfg_path
        self._planner = PlannerAgent(cfg.planner, llm_cfg_path)
        self._replanner = ReplannerAgent(cfg.replanner, llm_cfg_path)
        self._executor = ExecutorAgent(llm_cfg_path, agent_cfg=agent_cfg)
        self._events: list[PlanEvent] = []
        self._event_callbacks: list[Callable[[PlanEvent], None]] = []
        self._cycle = 0
        # Accessible by tools and WebUI while a plan is running
        self._current_doc: PlanDocument | None = None
        self._current_snapshots: SnapshotStore | None = None
        self._current_logger: PlanLogger | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self, question: str) -> PlanResult:
        plan_id = str(uuid.uuid4())
        # Shared file-I/O lock: serialises snapshot writes, shadow-file writes, and
        # pause-state dumps so that concurrent coroutines never interleave file I/O
        # for the same plan directory.
        plan_file_lock = asyncio.Lock()
        logger = PlanLogger(self._cfg.plan_dir, plan_id, self._cfg.log)
        snapshots = SnapshotStore(self._cfg.plan_dir, plan_id, file_lock=plan_file_lock)
        channel = HumanEditChannel(
            self._cfg.plan_dir, plan_id, self._cfg.shadow_poll_interval,
            file_lock=plan_file_lock,
        )

        await logger.info("plan_start", question=question[:200])

        self._current_logger = logger
        self._current_snapshots = snapshots

        # ── Plan phase ───────────────────────────────────────────────────────
        try:
            planner_result = await self._planner.run(question)
            doc: PlanDocument = planner_result.output
        except Exception as exc:
            await logger.error("planner_failed", exc=exc)
            raise

        doc.plan_id = plan_id
        task_count = len(doc.all_tasks())
        self._current_doc = doc
        self._emit(PlanStartEvent(plan_id=plan_id, title=doc.title, task_count=task_count))
        await logger.info("plan_created", title=doc.title, task_count=task_count)

        # Initial snapshot
        if "initial" in self._cfg.snapshot_triggers:
            snap = snapshots.save(doc, trigger="initial", cycle=0)
            self._emit(SnapshotEvent(plan_id=plan_id, snapshot_id=snap.snapshot_id, trigger="initial"))
            await logger.info("snapshot_saved", snapshot_id=snap.snapshot_id, trigger="initial")

        # Materialise shadow copy for human editing
        if self._cfg.human_edit:
            channel.materialize(doc)

        # ── Execution phase ──────────────────────────────────────────────────
        watch_task: asyncio.Task | None = None
        if self._cfg.human_edit:
            watch_task = asyncio.create_task(channel.watch(doc))

        try:
            await self._dispatch_all(doc, snapshots, channel, logger, plan_id, plan_file_lock)
        except Exception as exc:
            await logger.critical("dispatch_failed", exc=exc)
            if watch_task:
                watch_task.cancel()
            self._emit(PlanAbortEvent(plan_id=plan_id, reason=str(exc)))
            return PlanResult(plan_id=plan_id, status="failed", error=str(exc), doc=doc)
        finally:
            if watch_task:
                watch_task.cancel()

        # ── Final replan ─────────────────────────────────────────────────────
        decision = await self._call_replanner(
            doc, snapshots, logger, plan_id, trigger="on_plan_complete"
        )

        conclusion = decision.conclusion or doc.conclusion or ""
        status = "done" if decision.decision in ("done", "continue") else "aborted"
        self._emit(PlanCompleteEvent(plan_id=plan_id, conclusion=conclusion))
        await logger.info("plan_complete", status=status, conclusion=conclusion[:200])

        return PlanResult(plan_id=plan_id, status=status, answer=conclusion, doc=doc)

    # ── Event subscription ────────────────────────────────────────────────────

    def subscribe(self, callback: Callable[[PlanEvent], None]) -> None:
        self._event_callbacks.append(callback)

    def _emit(self, event: PlanEvent) -> None:
        self._events.append(event)
        for cb in self._event_callbacks:
            cb(event)

    # ── DAG dispatch ──────────────────────────────────────────────────────────

    async def _dispatch_all(
        self,
        doc: PlanDocument,
        snapshots: SnapshotStore,
        channel: HumanEditChannel,
        logger: PlanLogger,
        plan_id: str,
        plan_file_lock: asyncio.Lock,
    ) -> None:
        semaphore = Semaphore(self._cfg.parallel_limit)
        resource_cond: asyncio.Condition = asyncio.Condition()
        in_use_writes: set[str] = set()

        # Build done events for all tasks
        done_events: dict[str, asyncio.Event] = {
            t.task_id: asyncio.Event() for t in doc.all_tasks()
        }
        # Pre-set already completed tasks
        for t in doc.all_tasks():
            if t.status in (TaskStatus.done, TaskStatus.skipped):
                done_events[t.task_id].set()

        async def run_when_ready(task_id: str) -> None:
            task = doc.get_task(task_id)

            # Wait for all dependency events
            if task.depends_on:
                dep_tasks = [
                    done_events[dep].wait()
                    for dep in task.depends_on
                    if dep in done_events
                ]
                if dep_tasks:
                    await logger.debug("dag_dep_wait", task_id=task_id, waiting_for=task.depends_on)
                    await asyncio.gather(*dep_tasks)
                    await logger.debug("dag_dep_resolved", task_id=task_id)

            # May have been patched to skipped while waiting
            if task.status == TaskStatus.skipped:
                done_events[task_id].set()
                self._emit(TaskSkippedEvent(plan_id=plan_id, task_id=task_id, reason="patched"))
                await logger.info("task_skipped", task_id=task_id, reason="patched_while_waiting")
                return

            # Wait for resume if plan is paused
            if doc.metadata.paused:
                await logger.info("pause_detected", task_id=task_id)
                await self._emit_pause_snapshot(doc, snapshots, logger, plan_id, plan_file_lock)
                await doc._resume_event.wait()
                await logger.info("resume", task_id=task_id)

            # Drain human patches before executing
            if self._cfg.human_edit:
                patches = await channel.drain()
                if patches:
                    await self._apply_human_patches(
                        doc, patches, snapshots, channel, logger, plan_id
                    )
                    if task.status == TaskStatus.skipped:
                        done_events[task_id].set()
                        self._emit(TaskSkippedEvent(plan_id=plan_id, task_id=task_id, reason="human_skip"))
                        await logger.info("task_skipped", task_id=task_id, reason="human_patch")
                        return

                    # Handle !replan patch
                    if any(p.op == PatchOp.replan for p in patches):
                        await self._call_replanner(
                            doc, snapshots, logger, plan_id, trigger="on_human_request"
                        )

            # Resource guard: wait until none of task.writes are in-flight
            if task.writes:
                async with resource_cond:
                    while in_use_writes & set(task.writes):
                        await logger.debug("resource_wait", task_id=task_id, writes=task.writes)
                        await resource_cond.wait()
                    in_use_writes.update(task.writes)

            # Execute with concurrency limit
            async with semaphore:
                await logger.debug("dag_semaphore_acquire", task_id=task_id)
                self._emit(TaskStartEvent(
                    plan_id=plan_id, task_id=task_id,
                    module=task.module, profile=task.profile,
                ))
                self._emit(TaskRunningEvent(plan_id=plan_id, task_id=task_id))
                await logger.info("task_start", task_id=task_id, profile=task.profile)

                result = await self._executor.run(
                    instruction=task.description,
                    task=task,
                    doc=doc,
                )
                await logger.debug("dag_semaphore_release", task_id=task_id)

            # Release resource writes
            if task.writes:
                async with resource_cond:
                    in_use_writes.difference_update(task.writes)
                    resource_cond.notify_all()

            # Handle result
            done_events[task_id].set()

            if result.status == "done":
                preview = (result.output or "")[:200]
                self._emit(TaskCompleteEvent(plan_id=plan_id, task_id=task_id, result_preview=preview))
                await logger.info("task_complete", task_id=task_id, step_count=result.execution_ctx.step_count if result.execution_ctx else 0)

                # Snapshot if configured
                if "task_complete" in self._cfg.snapshot_triggers:
                    snap = await snapshots.save_async(doc, trigger=f"task_complete:{task_id}", cycle=self._cycle)
                    self._emit(SnapshotEvent(plan_id=plan_id, snapshot_id=snap.snapshot_id, trigger=f"task_complete:{task_id}"))

                # Check module completion
                if "on_task_complete" in self._cfg.replanner.triggers:
                    await self._call_replanner(doc, snapshots, logger, plan_id, trigger="on_task_complete")

                module_done = self._is_module_complete(task.module, doc)
                if module_done and "on_module_complete" in self._cfg.replanner.triggers:
                    await self._call_replanner(
                        doc, snapshots, logger, plan_id, trigger="on_module_complete"
                    )

            else:  # failed
                self._emit(TaskFailedEvent(plan_id=plan_id, task_id=task_id, error=task.error or ""))
                await logger.error("task_failed", task_id=task_id, error=task.error)

                if "on_task_failed" in self._cfg.replanner.triggers:
                    decision = await self._call_replanner(
                        doc, snapshots, logger, plan_id, trigger="on_task_failed"
                    )
                    # Activate new tasks added by replanner
                    new_tasks = [
                        t for t in doc.all_tasks()
                        if t.task_id not in done_events and t.status == TaskStatus.pending
                    ]
                    if new_tasks:
                        for t in new_tasks:
                            done_events[t.task_id] = asyncio.Event()
                        asyncio.gather(*[run_when_ready(t.task_id) for t in new_tasks])

        # Launch all pending tasks simultaneously
        pending = [t for t in doc.all_tasks() if t.status == TaskStatus.pending]
        if pending:
            await asyncio.gather(*[run_when_ready(t.task_id) for t in pending])

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_module_complete(self, module_name: str, doc: PlanDocument) -> bool:
        mod = doc.get_module(module_name)
        if mod is None:
            return False
        return all(
            t.status in (TaskStatus.done, TaskStatus.skipped, TaskStatus.failed)
            for t in mod.tasks
        )

    async def _call_replanner(
        self,
        doc: PlanDocument,
        snapshots: SnapshotStore,
        logger: PlanLogger,
        plan_id: str,
        trigger: str,
    ) -> ReplanDecision:
        self._cycle += 1

        if "pre_replan" in self._cfg.snapshot_triggers:
            snap = await snapshots.save_async(doc, trigger=f"pre_replan:{self._cycle}", cycle=self._cycle)
            self._emit(SnapshotEvent(plan_id=plan_id, snapshot_id=snap.snapshot_id, trigger=f"pre_replan:{self._cycle}"))

        await logger.info("replan_triggered", trigger=trigger, cycle=self._cycle)

        result = await self._replanner.run(
            instruction="",
            doc=doc,
            trigger=trigger,
            cycle=self._cycle,
        )
        decision: ReplanDecision = result.output

        await logger.info(
            "replan_decision",
            decision=decision.decision,
            confidence=decision.confidence,
            reason=decision.reason[:200],
            patches_count=len(decision.patches),
        )

        if decision.patches:
            from plan.patch import PlanDiff
            new_tasks = PlanDiff.apply(doc, decision.patches)
            self._emit(ReplanEvent(
                plan_id=plan_id,
                trigger=trigger,
                decision=decision.decision,
                patches_count=len(decision.patches),
                cycle=self._cycle,
            ))
            await logger.info("patches_applied", count=len(decision.patches))

        if decision.decision in ("done", "abort"):
            doc.conclusion = decision.conclusion

        return decision

    async def _apply_human_patches(
        self,
        doc: PlanDocument,
        patches: list[HumanPatch],
        snapshots: SnapshotStore,
        channel: HumanEditChannel,
        logger: PlanLogger,
        plan_id: str,
    ) -> None:
        if "pre_human_patch" in self._cfg.snapshot_triggers:
            snap = await snapshots.save_async(doc, trigger="pre_human_patch", cycle=self._cycle)
            self._emit(SnapshotEvent(plan_id=plan_id, snapshot_id=snap.snapshot_id, trigger="pre_human_patch"))

        from plan.patch import PlanDiff
        PlanDiff.apply(doc, patches)

        ops = [p.op.value for p in patches]
        self._emit(HumanPatchEvent(plan_id=plan_id, patches_count=len(patches), patch_ops=ops))
        await logger.info("patch_applied", patches_count=len(patches), ops=ops)

        channel.materialize(doc)

    async def _emit_pause_snapshot(
        self,
        doc: PlanDocument,
        snapshots: SnapshotStore,
        logger: PlanLogger,
        plan_id: str,
        plan_file_lock: asyncio.Lock,
    ) -> None:
        snap_path = Path(self._cfg.plan_dir) / plan_id / "paused_state.json"
        import json
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        async with plan_file_lock:
            snap_path.write_text(
                json.dumps(doc.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
            )
