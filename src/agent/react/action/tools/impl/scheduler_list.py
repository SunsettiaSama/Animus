from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel

from ....action.base import BaseAction


class SchedulerListArgs(BaseModel):
    pass


class SchedulerListAction(BaseAction):
    name: str = "scheduler_list"
    description: str = (
        "查看时间轴上所有已预约的 Agent 任务，返回任务 ID、名称、触发方式、状态和下次执行时间的摘要。"
        "无需参数。"
    )
    args_model: ClassVar[type[BaseModel]] = SchedulerListArgs

    engine: Any = None  # SchedulerEngine，构造时注入

    def execute(self, **kwargs) -> str:
        if self.engine is None:
            return "调度器未初始化。"

        tasks = self.engine.list_timeline()
        if not tasks:
            return "时间轴为空，暂无已预约任务。"

        lines: list[str] = [f"共 {len(tasks)} 个任务：", ""]
        for t in tasks:
            if t.trigger.type == "once":
                trigger_desc = f"一次性  触发时间: {t.trigger.at}"
            else:
                trigger_desc = f"周期 {t.trigger.interval_seconds}s  下次: {t.next_run_at}"
            lines.append(
                f"[{t.status.value}] {t.name}\n"
                f"  id: {t.id}\n"
                f"  触发: {trigger_desc}\n"
                f"  配置: {t.config_profile}"
            )
        return "\n".join(lines)
