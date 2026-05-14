from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any, Callable

from agent.flow.base.components.atomic_planner import AtomicPlanner
from agent.flow.base.budget import DecompositionBudget, TopologyKind
from agent.flow.base.components.node_spec import NodeManifest
from agent.flow.channel import HumanEditChannel
from agent.flow.config import OrchestratorConfig
from agent.flow.document import PlanDocument, PlanModule, PlanTask, TaskExecutionContext, TaskStatus
from agent.flow.execution_context import PlanExecutionContext
from agent.flow.event import (
    HumanPatchEvent,
    LifecycleStateEvent,
    PlanAbortEvent,
    PlanCompleteEvent,
    PlanEvent,
    PlanLifecycleState,
    PlannerStepEvent,
    PlanStartEvent,
    ReplanEvent,
    ReplannerCompleteEvent,
    ReplannerStartEvent,
    SnapshotEvent,
    TaskCompleteEvent,
    TaskFailedEvent,
    TaskRunningEvent,
    TaskSkippedEvent,
    TaskStartEvent,
)
from agent.flow.executor import ExecutorAgent
from agent.flow.log import PlanLogger
from agent.flow.patch import HumanPatch, PatchOp
from agent.flow.planner import PlannerAgent
from agent.flow.replanner import ReplanDecision, ReplannerAgent
from agent.flow.result import PlanResult
from agent.flow.snapshot import SnapshotStore


class FlowOrchestrator:
    def __init__(
        self,
        cfg: OrchestratorConfig,
        llm_cfg_path: str,
        agent_cfg: Any = None,
        execution_context: PlanExecutionContext | None = None,
    ) -> None:
        self._cfg = cfg
        self._llm_cfg_path = llm_cfg_path
        self._agent_cfg = agent_cfg
        # Agents are initialized lazily after execution context is set up
        self._planner: PlannerAgent | None = None
        self._replanner: ReplannerAgent | None = None
        self._executor_agent: ExecutorAgent | None = None
        self._atomic_planner: AtomicPlanner | None = None
        self._external_ctx = execution_context  # caller-supplied context (or None → build lazily)
        self._ctx: PlanExecutionContext | None = None
        self._events: list[PlanEvent] = []
        self._event_callbacks: list[Callable[[PlanEvent], None]] = []
        self._cycle = 0
        # Accessible by tools and WebUI while a plan is running
        self._current_doc: PlanDocument | None = None
        self._current_snapshots: SnapshotStore | None = None
        self._current_logger: PlanLogger | None = None
        self._lifecycle_state: PlanLifecycleState = PlanLifecycleState.idle
        self._current_plan_id: str | None = None
        # Per-task TAO step capture (task_id → list of step dicts)
        self._task_steps: dict[str, list[dict]] = {}
        self._main_loop = None

    def _build_agents(self) -> None:
        ctx = self._ctx
        assert ctx is not None
        self._planner = PlannerAgent(
            self._cfg.planner, self._llm_cfg_path, executor_pool=ctx.planner_pool
        )
        self._replanner = ReplannerAgent(
            self._cfg.replanner, self._llm_cfg_path, executor_pool=ctx.replanner_pool
        )
        # Wire replanner event sink so it can emit thinking events back to subscribers
        self._replanner.set_event_sink(self._emit_raw_dict)
        self._executor_agent = ExecutorAgent(
            self._llm_cfg_path, agent_cfg=self._agent_cfg, executor_pool=ctx.worker_pool
        )
        if self._cfg.decomposition.max_depth > 0:
            self._atomic_planner = AtomicPlanner(
                self._cfg.planner, self._llm_cfg_path, executor_pool=ctx.planner_pool
            )

    def _emit_raw_dict(self, d: dict) -> None:
        """Forward a raw dict emitted by sub-agents (e.g. replanner_thinking) to subscribers."""
        for cb in self._event_callbacks:
            cb(d)  # type: ignore[arg-type]

    # ── Atomic planning layer helpers ─────────────────────────────────────────

    def _task_to_manifest(self, task: PlanTask) -> NodeManifest:
        """Convert a PlanTask to a NodeManifest for AtomicPlanner assessment."""
        from agent.flow.base.components.observation import ObservationMode
        return NodeManifest(
            task_id=task.task_id,
            description=task.description,
            depends_on=tuple(task.depends_on),
            tool_package=task.params.get("tool_package") or (
                task.profile if task.profile not in ("minimal", "") else None
            ),
            max_steps=task.max_steps or task.params.get("max_steps"),
            system_note=task.params.get("system_note", ""),
            observation_mode=ObservationMode.distilled,
        )

    def _manifests_to_tasks(
        self,
        manifests: tuple[NodeManifest, ...],
        module_name: str,
        inherited_deps: list[str],
    ) -> list[PlanTask]:
        """Convert sub-manifests to PlanTask objects.

        Entry nodes (depends_on is empty in manifest) inherit the parent
        task's external dependencies so the sub-DAG starts only after its
        predecessors are complete.
        """
        tasks = []
        manifest_ids = {m.task_id for m in manifests}
        for m in manifests:
            is_entry = not m.depends_on or not any(d in manifest_ids for d in m.depends_on)
            external = inherited_deps if is_entry else []
            internal = [d for d in m.depends_on if d in manifest_ids]
            tasks.append(PlanTask(
                task_id=m.task_id,
                description=m.description,
                module=module_name,
                profile=m.tool_package or "minimal",
                max_steps=m.max_steps,
                depends_on=external + internal,
            ))
        return tasks

    async def _run_nested(
        self,
        parent_task: PlanTask,
        decision: Any,
        snapshots: SnapshotStore,
        channel: HumanEditChannel,
        logger: PlanLogger,
        plan_id: str,
        plan_file_lock: asyncio.Lock,
        child_budget: DecompositionBudget,
    ) -> str:
        """Run a nested sub-graph for a composite task, return exit node result."""
        sub_module = f"{parent_task.module}.{parent_task.task_id}"
        sub_tasks = self._manifests_to_tasks(decision.sub_manifests, sub_module, [])
        sub_plan_id = f"{plan_id}.{parent_task.task_id}"
        sub_doc = PlanDocument(
            plan_id=sub_plan_id,
            title=f"sub:{parent_task.task_id}",
            objective=parent_task.description,
            modules=[PlanModule(name=sub_module, tasks=sub_tasks)],
        )
        await self._dispatch_all(
            sub_doc, snapshots, channel, logger, sub_plan_id, plan_file_lock,
            budget=child_budget,
        )
        exit_id = decision.output_node_id or (sub_tasks[-1].task_id if sub_tasks else "")
        if exit_id:
            exit_task = sub_doc.get_task(exit_id)
            return exit_task.result or ""
        return ""

    # ── Lifecycle state properties ────────────────────────────────────────────

    @property
    def lifecycle_state(self) -> PlanLifecycleState:
        return self._lifecycle_state

    @property
    def current_plan_id(self) -> str | None:
        return self._current_plan_id

    def progress(self) -> tuple[int, int]:
        """Return (done_count, total_count) for the active plan."""
        if self._current_doc is None:
            return (0, 0)
        tasks = self._current_doc.all_tasks()
        done = sum(1 for t in tasks if t.status in (TaskStatus.done, TaskStatus.skipped, TaskStatus.failed))
        return (done, len(tasks))

    def running_tasks(self) -> list[str]:
        """Return task_ids currently in running state."""
        if self._current_doc is None:
            return []
        return [t.task_id for t in self._current_doc.all_tasks() if t.status == TaskStatus.running]

    def _set_lifecycle(self, state: PlanLifecycleState, plan_id: str) -> None:
        self._lifecycle_state = state
        self._emit(LifecycleStateEvent(plan_id=plan_id, state=state.value))

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self, question: str) -> PlanResult:
        plan_id = str(uuid.uuid4())
        self._current_plan_id = plan_id
        self._task_steps = {}
        self._main_loop = asyncio.get_running_loop()
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

        # Wire real-time log line push to SSE subscribers
        def _log_line_sink(record: dict) -> None:
            for cb in self._event_callbacks:
                cb(record)  # type: ignore[arg-type]
        logger.set_line_sink(_log_line_sink)

        # ── Plan phase ───────────────────────────────────────────────────────
        # Build a temporary context just for the planner phase (doc not available yet)
        _pre_ctx = self._external_ctx or PlanExecutionContext(
            plan_id=plan_id, effective_width=max(self._cfg.parallel_limit, 1)
        )
        self._ctx = _pre_ctx
        self._build_agents()

        self._set_lifecycle(PlanLifecycleState.planning, plan_id)
        assert self._planner is not None
        try:
            planner_result = await self._planner.run(
                question,
                step_callback=self._make_planner_callback(plan_id, "planning"),
            )
            doc: PlanDocument = planner_result.output
        except Exception as exc:
            await logger.error("planner_failed", exc=exc)
            self._set_lifecycle(PlanLifecycleState.failed, plan_id)
            raise

        doc.plan_id = plan_id
        task_count = len(doc.all_tasks())
        self._current_doc = doc

        # Rebuild execution context now that we have the DAG structure
        if self._external_ctx is None:
            self._ctx = PlanExecutionContext.from_config(
                plan_id=plan_id,
                parallel_limit=self._cfg.parallel_limit,
                doc=doc,
            )
            # Re-wire agents to new pools
            self._build_agents()

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
        self._set_lifecycle(PlanLifecycleState.running, plan_id)
        watch_task: asyncio.Task | None = None
        if self._cfg.human_edit:
            watch_task = asyncio.create_task(channel.watch(doc))

        try:
            await self._dispatch_all(doc, snapshots, channel, logger, plan_id, plan_file_lock)
        except Exception as exc:
            await logger.critical("dispatch_failed", exc=exc)
            if watch_task:
                watch_task.cancel()
            self._set_lifecycle(PlanLifecycleState.aborted, plan_id)
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
        final_state = PlanLifecycleState.done if status == "done" else PlanLifecycleState.aborted
        self._set_lifecycle(final_state, plan_id)
        self._emit(PlanCompleteEvent(plan_id=plan_id, conclusion=conclusion))
        await logger.info("plan_complete", status=status, conclusion=conclusion[:200])

        # Shut down execution context if we own it
        if self._external_ctx is None and self._ctx is not None:
            self._ctx.shutdown(wait=False)

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
        budget: DecompositionBudget | None = None,
    ) -> None:
        assert self._ctx is not None
        semaphore = self._ctx.semaphore
        resource_cond: asyncio.Condition = asyncio.Condition()
        in_use_writes: set[str] = set()
        effective_budget = budget if budget is not None else self._cfg.decomposition

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

            # ── Atomic planning layer ─────────────────────────────────────────
            if self._atomic_planner is not None and not effective_budget.exhausted:
                manifest = self._task_to_manifest(task)
                decision = await self._atomic_planner.assess(manifest, effective_budget)

                if decision.kind == TopologyKind.flat and decision.sub_manifests:
                    await logger.info("task_flat_expand", task_id=task_id,
                                      sub_count=len(decision.sub_manifests),
                                      reason=decision.reason[:120])
                    sub_tasks = self._manifests_to_tasks(
                        decision.sub_manifests, task.module, list(task.depends_on)
                    )
                    async with doc._lock:
                        mod = doc.get_module(task.module)
                        if mod:
                            mod.tasks.extend(sub_tasks)
                    for st in sub_tasks:
                        done_events[st.task_id] = asyncio.Event()
                    await asyncio.gather(*[run_when_ready(st.task_id) for st in sub_tasks])
                    exit_id = decision.output_node_id or sub_tasks[-1].task_id
                    exit_result = ""
                    if exit_id:
                        exit_task = doc.get_task(exit_id)
                        exit_result = exit_task.result or ""
                    exec_ctx = TaskExecutionContext(
                        task_id=task_id, status="done",
                        result_summary=exit_result[:300],
                    )
                    await doc.update_task(task_id, status=TaskStatus.done,
                                          result=exit_result, execution_ctx=exec_ctx)
                    done_events[task_id].set()
                    self._emit(TaskCompleteEvent(plan_id=plan_id, task_id=task_id,
                                                 result_preview=exit_result[:200]))
                    await logger.info("task_complete", task_id=task_id, kind="flat_expanded")
                    return

                if decision.kind == TopologyKind.nested and decision.sub_manifests:
                    await logger.info("task_nested_run", task_id=task_id,
                                      sub_count=len(decision.sub_manifests),
                                      reason=decision.reason[:120])
                    exit_result = await self._run_nested(
                        task, decision, snapshots, channel, logger,
                        plan_id, plan_file_lock, effective_budget.descend(),
                    )
                    exec_ctx = TaskExecutionContext(
                        task_id=task_id, status="done",
                        result_summary=exit_result[:300],
                    )
                    await doc.update_task(task_id, status=TaskStatus.done,
                                          result=exit_result, execution_ctx=exec_ctx)
                    done_events[task_id].set()
                    self._emit(TaskCompleteEvent(plan_id=plan_id, task_id=task_id,
                                                 result_preview=exit_result[:200]))
                    await logger.info("task_complete", task_id=task_id, kind="nested")
                    return
                # decision.kind == atomic: fall through to normal execution

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

                assert self._executor_agent is not None
                result = await self._executor_agent.run(
                    instruction=task.description,
                    task=task,
                    doc=doc,
                    step_callback=self._make_step_callback(task_id, plan_id),
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
                        await asyncio.gather(*[run_when_ready(t.task_id) for t in new_tasks])

        # Launch all pending tasks simultaneously
        pending = [t for t in doc.all_tasks() if t.status == TaskStatus.pending]
        if pending:
            await asyncio.gather(*[run_when_ready(t.task_id) for t in pending])

    # ── Planner step callback (thread-safe, called from executor thread) ──────

    def _make_planner_callback(self, plan_id: str, phase: str):
        loop = self._main_loop

        def cb(index: int, thought: str, action: str, obs: str) -> None:
            if loop is None or not loop.is_running():
                return
            ev = PlannerStepEvent(
                plan_id=plan_id,
                phase=phase,
                step_index=index,
                thought=thought,
                action=action,
                observation=obs,
            )
            loop.call_soon_threadsafe(self._emit, ev)

        return cb

    # ── Step callback (thread-safe, called from executor thread) ─────────────

    def _make_step_callback(self, task_id: str, plan_id: str):
        def _callback(event) -> None:
            # Duck-type StepEvent to avoid importing agent.react.tao (heavy deps).
            if not (hasattr(event, "index") and hasattr(event, "action")):
                return
            step = {
                "type":         "step",
                "index":        event.index,
                "thought":      getattr(event, "thought", None) or "",
                "action":       getattr(event, "action", None) or "",
                "action_input": getattr(event, "action_input", None),
                "observation":  getattr(event, "observation", None) or "",
            }
            if task_id not in self._task_steps:
                self._task_steps[task_id] = []
            self._task_steps[task_id].append(step)

            from agent.flow.event import TaskStepEvent
            ev = TaskStepEvent(plan_id=plan_id, task_id=task_id, step=step)
            loop = getattr(self, "_main_loop", None)
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(self._emit, ev)

        return _callback

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
        prev_state = self._lifecycle_state
        self._set_lifecycle(PlanLifecycleState.replanning, plan_id)

        if "pre_replan" in self._cfg.snapshot_triggers:
            snap = await snapshots.save_async(doc, trigger=f"pre_replan:{self._cycle}", cycle=self._cycle)
            self._emit(SnapshotEvent(plan_id=plan_id, snapshot_id=snap.snapshot_id, trigger=f"pre_replan:{self._cycle}"))

        await logger.info("replan_triggered", trigger=trigger, cycle=self._cycle)
        self._emit(ReplannerStartEvent(plan_id=plan_id, trigger=trigger, cycle=self._cycle))

        assert self._replanner is not None
        result = await self._replanner.run(
            instruction="",
            doc=doc,
            trigger=trigger,
            cycle=self._cycle,
            plan_id=plan_id,
        )
        decision: ReplanDecision = result.output

        await logger.info(
            "replan_decision",
            decision=decision.decision,
            confidence=decision.confidence,
            reason=decision.reason[:200],
            patches_count=len(decision.patches),
        )
        self._emit(ReplannerCompleteEvent(
            plan_id=plan_id,
            decision=decision.decision,
            reason=decision.reason[:200],
            patches_count=len(decision.patches),
        ))

        if decision.patches:
            from agent.flow.patch import PlanDiff
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
        else:
            # Restore previous state (running) after replanning unless terminal
            self._set_lifecycle(prev_state, plan_id)

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

        from agent.flow.patch import PlanDiff
        PlanDiff.apply(doc, patches)

        ops = [p.op.value for p in patches]
        self._emit(HumanPatchEvent(plan_id=plan_id, patches_count=len(patches), patch_ops=ops))
        await logger.info("patch_applied", patches_count=len(patches), ops=ops)

        channel.materialize(doc)

    def _handle_expansion_request(self, ev: "NodeExpansionRequestEvent") -> None:
        """
        Called from call_soon_threadsafe when a SubAgent requests node expansion.
        Emits the event for SSE subscribers and schedules an async replan coroutine.
        """
        from agent.flow.event import NodeExpansionRequestEvent
        self._emit(ev)
        # Pause the expanding node and trigger async replan
        if self._current_doc is not None:
            from agent.flow.document import TaskStatus
            task = self._current_doc.get_task(ev.task_id)
            task.status = TaskStatus.paused
        if self._main_loop is not None and self._main_loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._expansion_replan(ev),
                self._main_loop,
            )

    async def _expansion_replan(self, ev: "NodeExpansionRequestEvent") -> None:
        if self._current_doc is None or self._current_logger is None or self._current_snapshots is None:
            return
        trigger = f"expansion_request:{ev.task_id}"
        decision = await self._call_replanner(
            self._current_doc,
            self._current_snapshots,
            self._current_logger,
            ev.plan_id,
            trigger=trigger,
        )
        # Mark original node as done if replanner added replacement tasks
        if decision.patches and self._current_doc is not None:
            from agent.flow.document import TaskStatus
            task = self._current_doc.get_task(ev.task_id)
            if task.status == TaskStatus.paused:
                task.status = TaskStatus.skipped

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


PlanOrchestrator = FlowOrchestrator
