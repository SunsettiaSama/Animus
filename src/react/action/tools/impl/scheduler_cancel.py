from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from react.action.base import BaseAction


class SchedulerCancelArgs(BaseModel):
    task_id: str = Field(..., min_length=1, description="要取消的任务 ID")


class SchedulerCancelAction(BaseAction):
    name: str = "scheduler_cancel"
    description: str = (
        "取消时间轴上指定的 Agent 任务。"
        "参数：task_id（任务 ID，可通过 scheduler_list 查询）。"
        "已运行完成或已取消的任务无法再次取消。"
    )
    args_model: ClassVar[type[BaseModel]] = SchedulerCancelArgs

    engine: Any = None  # SchedulerEngine，构造时注入

    def execute(self, task_id: str, **kwargs) -> str:
        if self.engine is None:
            return "调度器未初始化。"

        task = self.engine.get(task_id)
        if task is None:
            return f"未找到任务：{task_id}"

        ok = self.engine.cancel(task_id)
        if ok:
            return f"已取消任务：{task.name}（id={task_id}）"
        return f"取消失败，任务可能已完成或已取消：{task_id}"
