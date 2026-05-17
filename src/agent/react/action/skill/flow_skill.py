from __future__ import annotations

import asyncio
import sys
import threading
from typing import Any, Callable, ClassVar

from pydantic import BaseModel, Field

from ...action.skill.base import BaseSkill


def _dict_with_flow_aliases(d: dict) -> dict:
    if "plan_id" in d and "flow_id" not in d:
        d = dict(d)
        d["flow_id"] = d["plan_id"]
    return d


class _FlowRunState:
    def __init__(self) -> None:
        self.done_event: threading.Event = threading.Event()
        self.result: Any = None
        self.error: str | None = None


class FlowSkillSet:
    def __init__(
        self,
        orchestrator: Any,
        event_sink: Callable[[dict], None] | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.event_sink = event_sink
        self._run_state: _FlowRunState | None = None

    def set_event_sink(self, sink: Callable[[dict], None] | None) -> None:
        self.event_sink = sink

    def _start_run(self) -> _FlowRunState:
        state = _FlowRunState()
        self._run_state = state
        return state

    @property
    def run_state(self) -> _FlowRunState | None:
        return self._run_state


class RunFlowArgs(BaseModel):
    question: str = Field(..., min_length=1, description="要由 Flow 多智能体编排器执行的复杂任务目标")


class FlowWaitArgs(BaseModel):
    timeout_seconds: int = Field(
        300,
        description="等待 Flow 完成的最长时间（秒）。超时后返回当前进度，可再次调用继续等待。",
    )


class FlowSkipArgs(BaseModel):
    task_id: str = Field(..., description="要跳过的任务 task_id")
    cascade: bool = Field(False, description="是否级联跳过所有依赖该任务的后继任务")


class RunFlowSkill(BaseSkill):
    name: str = "run_flow"
    description: str = (
        "使用 Flow 多智能体编排（DAG + Plan-and-Execute）异步启动复杂任务，立即返回 flow_id（与 plan_id 同义）。"
        "编排器在后台规划、拆分子任务、并行执行，并在需要时重规划。"
        "可调用 flow_wait() 阻塞等待完成。"
        "参数：question（任务目标描述）。"
    )
    skill_type: str = "chain"
    version: str = "1.0.0"
    args_model: ClassVar[type[BaseModel]] = RunFlowArgs

    skill_set: Any = None

    def execute(self, question: str, **kwargs) -> str:
        if self.skill_set is None:
            return "[run_flow] 错误：FlowSkillSet 未初始化。"

        orchestrator = self.skill_set.orchestrator
        event_sink = self.skill_set.event_sink
        run_state = self.skill_set._start_run()

        _on_event_ref: list = []

        if event_sink is not None:
            def _on_event(event) -> None:
                event_sink(_serialize_flow_event(event))

            _on_event_ref.append(_on_event)
            orchestrator.subscribe(_on_event)

        sm = sys.modules.get("state")
        if sm is not None and hasattr(sm, "get_state"):
            state = sm.get_state()
            state.active_orchestrator = orchestrator

        def _run_thread() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(orchestrator.run(question))
            run_state.result = result
            run_state.done_event.set()
            loop.close()
            if _on_event_ref and _on_event_ref[0] in orchestrator._event_callbacks:
                orchestrator._event_callbacks.remove(_on_event_ref[0])

        thread = threading.Thread(target=_run_thread, daemon=True)
        thread.start()

        flow_id = orchestrator.current_plan_id or "(generating…)"
        return (
            f"[run_flow] Flow 已在后台启动。\n"
            f"flow_id: {flow_id} | 状态: PLANNING\n"
            f"可调用 flow_wait() 阻塞等待最终结果。"
        )


class FlowStatusSkill(BaseSkill):
    name: str = "flow_status"
    description: str = "查看当前 Flow 的实时状态（生命周期、任务进度、正在执行的任务）。无需参数。"
    skill_type: str = "simple"
    version: str = "1.0.0"
    args_model: ClassVar[type[BaseModel] | None] = None

    skill_set: Any = None

    def execute(self, **kwargs) -> str:
        if self.skill_set is None:
            return "[flow_status] 错误：FlowSkillSet 未初始化。"
        return _format_flow_status(self.skill_set.orchestrator)


class FlowWaitSkill(BaseSkill):
    name: str = "flow_wait"
    description: str = (
        "阻塞等待当前 Flow 完成。参数：timeout_seconds（默认 300）。"
        "超时后返回当前进度，可再次调用。"
    )
    skill_type: str = "simple"
    version: str = "1.0.0"
    args_model: ClassVar[type[BaseModel]] = FlowWaitArgs

    skill_set: Any = None

    def execute(self, timeout_seconds: int = 300, **kwargs) -> str:
        if self.skill_set is None:
            return "[flow_wait] 错误：FlowSkillSet 未初始化。"
        run_state = self.skill_set.run_state
        if run_state is None:
            return "[flow_wait] 当前没有正在运行的 Flow，请先调用 run_flow()。"

        completed = run_state.done_event.wait(timeout=timeout_seconds)
        if not completed:
            status_str = _format_flow_status(self.skill_set.orchestrator)
            return (
                f"[flow_wait] 等待超时（{timeout_seconds}s）。\n"
                f"{status_str}\n"
                "可再次调用 flow_wait() 或 flow_status()。"
            )

        if run_state.error:
            return f"[flow_wait] Flow 执行失败：{run_state.error}"

        result = run_state.result
        if result is None:
            return "[flow_wait] Flow 已完成但未返回结果。"

        return f"[flow] 完成 status={result.status}\n{result.answer}"


class FlowSkipSkill(BaseSkill):
    name: str = "flow_skip"
    description: str = (
        "跳过 Flow 中指定任务。cascade=true 时级联跳过依赖该任务的后继。"
        "参数：task_id，cascade（可选）。"
    )
    skill_type: str = "simple"
    version: str = "1.0.0"
    args_model: ClassVar[type[BaseModel]] = FlowSkipArgs

    skill_set: Any = None

    def execute(self, task_id: str, cascade: bool = False, **kwargs) -> str:
        if self.skill_set is None:
            return "[flow_skip] 错误：FlowSkillSet 未初始化。"
        doc = getattr(self.skill_set.orchestrator, "_current_doc", None)
        if doc is None:
            return "[flow_skip] 当前没有正在运行的 Flow。"
        doc.skip(task_id, cascade=cascade)
        msg = f"任务 '{task_id}' 已标记为跳过"
        if cascade:
            msg += "（级联：后继依赖任务也被跳过）"
        return msg


def _format_flow_status(orchestrator: Any) -> str:
    from agent.flow.cluster.document import TaskStatus

    doc = getattr(orchestrator, "_current_doc", None)
    if doc is None:
        lifecycle = getattr(orchestrator, "_lifecycle_state", None)
        state_str = lifecycle.value if lifecycle is not None else "idle"
        return f"[flow_status] 状态: {state_str} | 暂无活跃任务文档。"

    lifecycle = orchestrator.lifecycle_state
    done_count, total = orchestrator.progress()
    running = orchestrator.running_tasks()
    pct = int(done_count / total * 100) if total > 0 else 0

    lines = [
        f"[Flow {orchestrator.current_plan_id}] 状态: {lifecycle.value.upper()} | "
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


def _serialize_flow_event(event: Any) -> dict:
    if isinstance(event, dict):
        return _dict_with_flow_aliases(event)
    from agent.flow.cluster.event import (
        HumanPatchEvent,
        LifecycleStateEvent,
        LogLineEvent,
        NodeExpansionRequestEvent,
        PlanAbortEvent,
        PlanCompleteEvent,
        PlanStartEvent,
        PlannerStepEvent,
        ReplanEvent,
        ReplannerCompleteEvent,
        ReplannerStartEvent,
        ReplannerThinkingEvent,
        SnapshotEvent,
        TaskCompleteEvent,
        TaskFailedEvent,
        TaskRunningEvent,
        TaskSkippedEvent,
        TaskStartEvent,
        TaskStepEvent,
    )
    if isinstance(event, PlanStartEvent):
        return _dict_with_flow_aliases(
            {"type": "plan_start", "plan_id": event.plan_id, "title": event.title, "task_count": event.task_count}
        )
    if isinstance(event, TaskStartEvent):
        return _dict_with_flow_aliases(
            {"type": "task_start", "plan_id": event.plan_id, "task_id": event.task_id, "module": event.module, "profile": event.profile}
        )
    if isinstance(event, TaskRunningEvent):
        return _dict_with_flow_aliases({"type": "task_running", "plan_id": event.plan_id, "task_id": event.task_id})
    if isinstance(event, TaskCompleteEvent):
        return _dict_with_flow_aliases(
            {"type": "task_complete", "plan_id": event.plan_id, "task_id": event.task_id, "result_preview": event.result_preview}
        )
    if isinstance(event, TaskFailedEvent):
        return _dict_with_flow_aliases({"type": "task_failed", "plan_id": event.plan_id, "task_id": event.task_id, "error": event.error})
    if isinstance(event, TaskSkippedEvent):
        return _dict_with_flow_aliases({"type": "task_skipped", "plan_id": event.plan_id, "task_id": event.task_id, "reason": event.reason})
    if isinstance(event, ReplanEvent):
        return _dict_with_flow_aliases(
            {
                "type": "replan",
                "plan_id": event.plan_id,
                "trigger": event.trigger,
                "decision": event.decision,
                "patches_count": event.patches_count,
                "cycle": event.cycle,
            }
        )
    if isinstance(event, HumanPatchEvent):
        return _dict_with_flow_aliases(
            {"type": "human_patch", "plan_id": event.plan_id, "patches_count": event.patches_count, "patch_ops": event.patch_ops}
        )
    if isinstance(event, SnapshotEvent):
        return _dict_with_flow_aliases(
            {"type": "snapshot", "plan_id": event.plan_id, "snapshot_id": event.snapshot_id, "trigger": event.trigger}
        )
    if isinstance(event, PlanCompleteEvent):
        return _dict_with_flow_aliases({"type": "plan_complete", "plan_id": event.plan_id, "conclusion": event.conclusion})
    if isinstance(event, PlanAbortEvent):
        return _dict_with_flow_aliases({"type": "plan_abort", "plan_id": event.plan_id, "reason": event.reason})
    if isinstance(event, LifecycleStateEvent):
        return _dict_with_flow_aliases({"type": "lifecycle_state", "plan_id": event.plan_id, "state": event.state})
    if isinstance(event, TaskStepEvent):
        return _dict_with_flow_aliases({"type": "task_step", "plan_id": event.plan_id, "task_id": event.task_id, "step": event.step})
    if isinstance(event, PlannerStepEvent):
        return _dict_with_flow_aliases(
            {
                "type": "planner_step",
                "plan_id": event.plan_id,
                "phase": event.phase,
                "step_index": event.step_index,
                "thought": event.thought,
                "action": event.action,
                "observation": event.observation,
            }
        )
    if isinstance(event, ReplannerStartEvent):
        return _dict_with_flow_aliases(
            {"type": "replanner_start", "plan_id": event.plan_id, "trigger": event.trigger, "cycle": event.cycle}
        )
    if isinstance(event, ReplannerCompleteEvent):
        return _dict_with_flow_aliases(
            {
                "type": "replanner_complete",
                "plan_id": event.plan_id,
                "decision": event.decision,
                "reason": event.reason,
                "patches_count": event.patches_count,
            }
        )
    if isinstance(event, ReplannerThinkingEvent):
        return _dict_with_flow_aliases(
            {"type": "replanner_thinking", "plan_id": event.plan_id, "stage": event.stage, "cycle": event.cycle}
        )
    if isinstance(event, NodeExpansionRequestEvent):
        return _dict_with_flow_aliases(
            {
                "type": "node_expansion_request",
                "plan_id": event.plan_id,
                "task_id": event.task_id,
                "reason": event.reason,
                "suggested_subtasks": event.suggested_subtasks,
            }
        )
    if isinstance(event, LogLineEvent):
        return _dict_with_flow_aliases(
            {"type": "log_line", "plan_id": event.plan_id, "level": event.level, "event": event.event, **event.payload}
        )
    return {"type": "unknown"}
