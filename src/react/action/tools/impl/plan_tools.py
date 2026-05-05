from __future__ import annotations

import asyncio
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from react.action.base import BaseAction


# ── plan_status ───────────────────────────────────────────────────────────────

class PlanStatusArgs(BaseModel):
    pass


class PlanStatusAction(BaseAction):
    name: str = "plan_status"
    description: str = (
        "查看当前编排计划的执行状态，包括所有任务的状态、已完成结果摘要和待执行任务列表。"
        "无需任何参数。"
    )
    args_model: ClassVar[type[BaseModel]] = PlanStatusArgs

    orchestrator: Any = None

    def execute(self, **kwargs: Any) -> str:
        if self.orchestrator is None:
            return "编排器未初始化。"
        doc = getattr(self.orchestrator, "_current_doc", None)
        if doc is None:
            return "当前没有正在运行的计划。"
        lines = [f"# Plan: {doc.title}", f"Objective: {doc.objective}", ""]
        for mod in doc.modules:
            lines.append(f"## Module: {mod.name}")
            for task in mod.tasks:
                lines.append(f"  [{task.status.value}] {task.task_id} (profile:{task.profile})")
                if task.result:
                    lines.append(f"    Result: {task.result[:100]}")
                if task.error:
                    lines.append(f"    Error: {task.error[:100]}")
        return "\n".join(lines)


# ── plan_skip ─────────────────────────────────────────────────────────────────

class PlanSkipArgs(BaseModel):
    task_id: str = Field(..., description="要跳过的任务 task_id")
    cascade: bool = Field(False, description="是否级联跳过依赖此任务的所有后继任务")


class PlanSkipAction(BaseAction):
    name: str = "plan_skip"
    description: str = (
        "跳过指定任务。cascade=true 时同时跳过所有依赖该任务的后继任务。"
        "参数：task_id（要跳过的任务ID），cascade（可选，默认false）。"
    )
    args_model: ClassVar[type[BaseModel]] = PlanSkipArgs

    orchestrator: Any = None

    def execute(self, task_id: str, cascade: bool = False, **kwargs: Any) -> str:
        if self.orchestrator is None:
            return "编排器未初始化。"
        doc = getattr(self.orchestrator, "_current_doc", None)
        if doc is None:
            return "当前没有正在运行的计划。"
        doc.skip(task_id, cascade=cascade)
        msg = f"任务 '{task_id}' 已标记为跳过"
        if cascade:
            msg += "（级联模式：依赖此任务的后继也被跳过）"
        return msg


# ── plan_pause ────────────────────────────────────────────────────────────────

class PlanPauseArgs(BaseModel):
    pass


class PlanPauseAction(BaseAction):
    name: str = "plan_pause"
    description: str = (
        "暂停当前编排计划。暂停后不再派发新任务，已在运行的任务可继续完成。"
        "无需任何参数。"
    )
    args_model: ClassVar[type[BaseModel]] = PlanPauseArgs

    orchestrator: Any = None

    def execute(self, **kwargs: Any) -> str:
        if self.orchestrator is None:
            return "编排器未初始化。"
        doc = getattr(self.orchestrator, "_current_doc", None)
        if doc is None:
            return "当前没有正在运行的计划。"
        doc.pause()
        return "计划已暂停。修改 shadow 文件后清除 paused 标记即可恢复。"


# ── plan_snapshot ─────────────────────────────────────────────────────────────

class PlanSnapshotArgs(BaseModel):
    pass


class PlanSnapshotAction(BaseAction):
    name: str = "plan_snapshot"
    description: str = (
        "手动保存当前计划状态的快照，用于后续回滚。无需任何参数。"
    )
    args_model: ClassVar[type[BaseModel]] = PlanSnapshotArgs

    orchestrator: Any = None

    def execute(self, **kwargs: Any) -> str:
        if self.orchestrator is None:
            return "编排器未初始化。"
        snapshots = getattr(self.orchestrator, "_current_snapshots", None)
        doc = getattr(self.orchestrator, "_current_doc", None)
        if snapshots is None or doc is None:
            return "当前没有正在运行的计划。"
        snap = snapshots.save(doc, trigger="manual", cycle=0)
        return f"快照已保存：{snap.snapshot_id}"


# ── plan_rollback ─────────────────────────────────────────────────────────────

class PlanRollbackArgs(BaseModel):
    snapshot_id: str = Field(..., description="要回滚到的快照 ID（由 plan_snapshot 返回）")


class PlanRollbackAction(BaseAction):
    name: str = "plan_rollback"
    description: str = (
        "回滚计划到指定快照状态。running 状态的任务重置为 pending，done 任务保留结果。"
        "参数：snapshot_id（快照ID）。"
    )
    args_model: ClassVar[type[BaseModel]] = PlanRollbackArgs

    orchestrator: Any = None

    def execute(self, snapshot_id: str, **kwargs: Any) -> str:
        if self.orchestrator is None:
            return "编排器未初始化。"
        snapshots = getattr(self.orchestrator, "_current_snapshots", None)
        if snapshots is None:
            return "当前没有正在运行的计划。"
        new_doc = snapshots.rollback(snapshot_id)
        self.orchestrator._current_doc = new_doc
        return f"已回滚到快照 {snapshot_id}，计划状态已恢复。"


# ── run_plan ──────────────────────────────────────────────────────────────────

class RunPlanArgs(BaseModel):
    question: str = Field(..., description="要由 PlanOrchestrator 执行的任务目标/问题")


class RunPlanAction(BaseAction):
    name: str = "run_plan"
    description: str = (
        "使用多智能体编排计划（Plan-and-Execute）来完成一个复杂任务。"
        "编排器将自动规划、拆分任务、并行执行，并在需要时进行重新规划。"
        "参数：question（任务目标描述）。"
    )
    args_model: ClassVar[type[BaseModel]] = RunPlanArgs

    orchestrator: Any = None

    def execute(self, question: str, **kwargs: Any) -> str:
        if self.orchestrator is None:
            return "编排器未初始化。"
        result = asyncio.get_event_loop().run_until_complete(
            self.orchestrator.run(question)
        )
        return f"[plan:{result.plan_id}] status={result.status}\n{result.answer}"
