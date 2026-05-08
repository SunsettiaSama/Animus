from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, ClassVar

from pydantic import BaseModel, Field

from ...action.skill.base import BaseSkill


# ── Shared state container ─────────────────────────────────────────────────────

class _PlanRunState:
    """
    Holds the mutable state for one in-flight plan run.
    Shared between RunPlanSkill and the wait/status/skip skills via the
    PlanSkillSet coordinator injected into each skill.
    """

    def __init__(self) -> None:
        self.done_event: threading.Event = threading.Event()
        self.result: Any = None          # PlanResult once done
        self.error: str | None = None    # error message if thread crashed


# ── PlanSkillSet ──────────────────────────────────────────────────────────────

class PlanSkillSet:
    """
    Coordinator that wires the four plan skills to a shared PlanOrchestrator
    and a common _PlanRunState.  TaoLoop creates one instance per PlanOrchestrator
    and injects it into each skill via the `skill_set` attribute.
    """

    def __init__(
        self,
        orchestrator: Any,                         # PlanOrchestrator
        event_sink: Callable[[dict], None] | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.event_sink = event_sink
        self._run_state: _PlanRunState | None = None

    def set_event_sink(self, sink: Callable[[dict], None] | None) -> None:
        self.event_sink = sink

    # Called by RunPlanSkill before spawning the background thread
    def _start_run(self) -> _PlanRunState:
        state = _PlanRunState()
        self._run_state = state
        return state

    @property
    def run_state(self) -> _PlanRunState | None:
        return self._run_state


# ── Arg models ────────────────────────────────────────────────────────────────

class RunPlanArgs(BaseModel):
    question: str = Field(..., min_length=1, description="要由多智能体编排器执行的复杂任务目标")


class PlanWaitArgs(BaseModel):
    timeout_seconds: int = Field(
        300,
        description="等待计划完成的最长时间（秒）。超时后返回当前进度，可再次调用继续等待。",
    )


class PlanSkipArgs(BaseModel):
    task_id: str = Field(..., description="要跳过的任务 task_id")
    cascade: bool = Field(False, description="是否级联跳过所有依赖该任务的后继任务")


# ── run_plan ──────────────────────────────────────────────────────────────────

class RunPlanSkill(BaseSkill):
    name: str = "run_plan"
    description: str = (
        "使用多智能体编排计划（Plan-and-Execute）异步启动一个复杂任务，立即返回 plan_id。"
        "编排器将在后台自动规划、拆分子任务、并行执行，并在需要时触发重规划。"
        "启动后可通过提示上下文自动获得进度更新，或调用 plan_wait() 阻塞等待完成结果。"
        "参数：question（任务目标描述）。"
    )
    skill_type: str = "chain"
    version: str = "1.0.0"
    args_model: ClassVar[type[BaseModel]] = RunPlanArgs

    skill_set: Any = None  # PlanSkillSet，由 TaoLoop 注入

    def execute(self, question: str, **kwargs) -> str:
        if self.skill_set is None:
            return "[run_plan] 错误：PlanSkillSet 未初始化。"

        orchestrator = self.skill_set.orchestrator
        event_sink = self.skill_set.event_sink
        run_state = self.skill_set._start_run()

        # Register event_sink subscriber before running
        _on_event_ref: list = []

        if event_sink is not None:
            def _on_event(event) -> None:
                event_sink(_serialize_plan_event(event))

            _on_event_ref.append(_on_event)
            orchestrator.subscribe(_on_event)

        # Register orchestrator globally so REST APIs can find it
        _state_ref: list = []
        try:
            from state import get_state
            state = get_state()
            state.active_orchestrator = orchestrator
            _state_ref.append(state)
        except Exception:
            pass

        def _run_thread() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(orchestrator.run(question))
            run_state.result = result
            run_state.done_event.set()
            loop.close()
            # Unsubscribe event callback to prevent leaks on re-use
            if _on_event_ref and _on_event_ref[0] in orchestrator._event_callbacks:
                orchestrator._event_callbacks.remove(_on_event_ref[0])

        thread = threading.Thread(target=_run_thread, daemon=True)
        thread.start()

        plan_id = orchestrator.current_plan_id or "(generating…)"
        return (
            f"[run_plan] 多智能体计划已在后台启动。\n"
            f"plan_id: {plan_id} | 状态: PLANNING\n"
            f"进度将自动显示在上下文中。调用 plan_wait() 阻塞等待最终结果。"
        )


# ── plan_status ───────────────────────────────────────────────────────────────

class PlanStatusSkill(BaseSkill):
    name: str = "plan_status"
    description: str = (
        "查看当前多智能体计划的实时执行状态，包括生命周期阶段、任务进度和正在执行的任务列表。"
        "无需参数。"
    )
    skill_type: str = "simple"
    version: str = "1.0.0"
    args_model: ClassVar[type[BaseModel] | None] = None

    skill_set: Any = None  # PlanSkillSet，由 TaoLoop 注入

    def execute(self, **kwargs) -> str:
        if self.skill_set is None:
            return "[plan_status] 错误：PlanSkillSet 未初始化。"
        return _format_plan_status(self.skill_set.orchestrator)


# ── plan_wait ─────────────────────────────────────────────────────────────────

class PlanWaitSkill(BaseSkill):
    name: str = "plan_wait"
    description: str = (
        "阻塞等待当前多智能体计划完成，返回最终结论和状态。"
        "参数：timeout_seconds（默认 300 秒）。超时后返回当前进度，可再次调用继续等待。"
    )
    skill_type: str = "simple"
    version: str = "1.0.0"
    args_model: ClassVar[type[BaseModel]] = PlanWaitArgs

    skill_set: Any = None  # PlanSkillSet，由 TaoLoop 注入

    def execute(self, timeout_seconds: int = 300, **kwargs) -> str:
        if self.skill_set is None:
            return "[plan_wait] 错误：PlanSkillSet 未初始化。"
        run_state = self.skill_set.run_state
        if run_state is None:
            return "[plan_wait] 当前没有正在运行的计划，请先调用 run_plan()。"

        completed = run_state.done_event.wait(timeout=timeout_seconds)
        if not completed:
            status_str = _format_plan_status(self.skill_set.orchestrator)
            return (
                f"[plan_wait] 等待超时（{timeout_seconds}s）。\n"
                f"{status_str}\n"
                "可再次调用 plan_wait() 继续等待，或调用 plan_status() 查看详情。"
            )

        if run_state.error:
            return f"[plan_wait] 计划执行失败：{run_state.error}"

        result = run_state.result
        if result is None:
            return "[plan_wait] 计划已完成但未返回结果。"

        return f"[plan] 完成 status={result.status}\n{result.answer}"


# ── plan_skip ─────────────────────────────────────────────────────────────────

class PlanSkipSkill(BaseSkill):
    name: str = "plan_skip"
    description: str = (
        "跳过当前多智能体计划中的指定任务。cascade=true 时同时跳过所有依赖该任务的后继任务。"
        "参数：task_id（要跳过的任务ID），cascade（可选，默认 false）。"
    )
    skill_type: str = "simple"
    version: str = "1.0.0"
    args_model: ClassVar[type[BaseModel]] = PlanSkipArgs

    skill_set: Any = None  # PlanSkillSet，由 TaoLoop 注入

    def execute(self, task_id: str, cascade: bool = False, **kwargs) -> str:
        if self.skill_set is None:
            return "[plan_skip] 错误：PlanSkillSet 未初始化。"
        doc = getattr(self.skill_set.orchestrator, "_current_doc", None)
        if doc is None:
            return "[plan_skip] 当前没有正在运行的计划。"
        doc.skip(task_id, cascade=cascade)
        msg = f"任务 '{task_id}' 已标记为跳过"
        if cascade:
            msg += "（级联模式：依赖此任务的后继也被跳过）"
        return msg


# ── Shared formatting helper ───────────────────────────────────────────────────

def _format_plan_status(orchestrator: Any) -> str:
    from plan.document import TaskStatus

    doc = getattr(orchestrator, "_current_doc", None)
    if doc is None:
        lifecycle = getattr(orchestrator, "_lifecycle_state", None)
        state_str = lifecycle.value if lifecycle is not None else "idle"
        return f"[plan_status] 状态: {state_str} | 暂无活跃计划文档。"

    lifecycle = orchestrator.lifecycle_state
    done_count, total = orchestrator.progress()
    running = orchestrator.running_tasks()
    pct = int(done_count / total * 100) if total > 0 else 0

    lines = [
        f"[Plan {orchestrator.current_plan_id}] 状态: {lifecycle.value.upper()} | "
        f"进度: {done_count}/{total} ({pct}%)"
    ]

    if running:
        tasks_str = ", ".join(
            f"{tid}({doc.get_task(tid).profile})" if doc.get_task(tid) else tid
            for tid in running
        )
        lines.append(f"正在执行: {tasks_str}")

    completed = [t.task_id for t in doc.all_tasks() if t.status == TaskStatus.done]
    if completed:
        lines.append(f"已完成: {', '.join(completed)}")

    pending = [t.task_id for t in doc.all_tasks() if t.status.value == "pending"]
    if pending:
        lines.append(f"待执行: {', '.join(pending)}")

    failed = [t.task_id for t in doc.all_tasks() if t.status == TaskStatus.failed]
    if failed:
        lines.append(f"失败: {', '.join(failed)}")

    return "\n".join(lines)


# ── Plan event serialisation (no webui dependency) ────────────────────────────

def _serialize_plan_event(event: Any) -> dict:
    """Convert a PlanEvent dataclass or raw dict to a JSON-serialisable dict for the event_sink."""
    # Raw dicts are forwarded as-is (e.g. replanner_thinking, log_line)
    if isinstance(event, dict):
        return event
    from plan.event import (
        HumanPatchEvent, LifecycleStateEvent,
        PlanAbortEvent, PlanCompleteEvent, PlanStartEvent,
        PlannerStepEvent, ReplanEvent, ReplannerCompleteEvent,
        ReplannerStartEvent, ReplannerThinkingEvent,
        SnapshotEvent, TaskCompleteEvent, TaskFailedEvent,
        TaskRunningEvent, TaskSkippedEvent, TaskStartEvent,
        TaskStepEvent, NodeExpansionRequestEvent, LogLineEvent,
    )
    if isinstance(event, PlanStartEvent):
        return {"type": "plan_start", "plan_id": event.plan_id, "title": event.title, "task_count": event.task_count}
    if isinstance(event, TaskStartEvent):
        return {"type": "task_start", "plan_id": event.plan_id, "task_id": event.task_id, "module": event.module, "profile": event.profile}
    if isinstance(event, TaskRunningEvent):
        return {"type": "task_running", "plan_id": event.plan_id, "task_id": event.task_id}
    if isinstance(event, TaskCompleteEvent):
        return {"type": "task_complete", "plan_id": event.plan_id, "task_id": event.task_id, "result_preview": event.result_preview}
    if isinstance(event, TaskFailedEvent):
        return {"type": "task_failed", "plan_id": event.plan_id, "task_id": event.task_id, "error": event.error}
    if isinstance(event, TaskSkippedEvent):
        return {"type": "task_skipped", "plan_id": event.plan_id, "task_id": event.task_id, "reason": event.reason}
    if isinstance(event, ReplanEvent):
        return {"type": "replan", "plan_id": event.plan_id, "trigger": event.trigger, "decision": event.decision, "patches_count": event.patches_count, "cycle": event.cycle}
    if isinstance(event, HumanPatchEvent):
        return {"type": "human_patch", "plan_id": event.plan_id, "patches_count": event.patches_count, "patch_ops": event.patch_ops}
    if isinstance(event, SnapshotEvent):
        return {"type": "snapshot", "plan_id": event.plan_id, "snapshot_id": event.snapshot_id, "trigger": event.trigger}
    if isinstance(event, PlanCompleteEvent):
        return {"type": "plan_complete", "plan_id": event.plan_id, "conclusion": event.conclusion}
    if isinstance(event, PlanAbortEvent):
        return {"type": "plan_abort", "plan_id": event.plan_id, "reason": event.reason}
    if isinstance(event, LifecycleStateEvent):
        return {"type": "lifecycle_state", "plan_id": event.plan_id, "state": event.state}
    if isinstance(event, TaskStepEvent):
        return {"type": "task_step", "plan_id": event.plan_id, "task_id": event.task_id, "step": event.step}
    if isinstance(event, PlannerStepEvent):
        return {
            "type": "planner_step",
            "plan_id": event.plan_id,
            "phase": event.phase,
            "step_index": event.step_index,
            "thought": event.thought,
            "action": event.action,
            "observation": event.observation,
        }
    if isinstance(event, ReplannerStartEvent):
        return {"type": "replanner_start", "plan_id": event.plan_id, "trigger": event.trigger, "cycle": event.cycle}
    if isinstance(event, ReplannerCompleteEvent):
        return {
            "type": "replanner_complete",
            "plan_id": event.plan_id,
            "decision": event.decision,
            "reason": event.reason,
            "patches_count": event.patches_count,
        }
    if isinstance(event, ReplannerThinkingEvent):
        return {"type": "replanner_thinking", "plan_id": event.plan_id, "stage": event.stage, "cycle": event.cycle}
    if isinstance(event, NodeExpansionRequestEvent):
        return {
            "type": "node_expansion_request",
            "plan_id": event.plan_id,
            "task_id": event.task_id,
            "reason": event.reason,
            "suggested_subtasks": event.suggested_subtasks,
        }
    if isinstance(event, LogLineEvent):
        return {"type": "log_line", "plan_id": event.plan_id, "level": event.level, "event": event.event, **event.payload}
    return {"type": "unknown"}
