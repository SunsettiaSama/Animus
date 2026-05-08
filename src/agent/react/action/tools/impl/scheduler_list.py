from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel

from ....action.base import BaseAction


class SchedulerListArgs(BaseModel):
    pass


class SchedulerListAction(BaseAction):
    name: str = "scheduler_list"
    description: str = (
        "查看时间轴上所有已预约的 Agent 任务，返回任务 ID、名称、触发方式、状态、投递方式和下次执行时间的摘要。"
        "无需参数。"
    )
    args_model: ClassVar[type[BaseModel]] = SchedulerListArgs

    engine: Any = None

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
            elif t.trigger.type == "cron":
                trigger_desc = f"Cron [{t.trigger.cron_expr}]  下次: {t.next_run_at}"
            else:
                trigger_desc = f"周期 {t.trigger.interval_seconds}s  下次: {t.next_run_at}"

            retry_info = ""
            if t.max_retries > 0:
                retry_info = f"\n  重试: {t.retry_count}/{t.max_retries}"

            chain_info = ""
            if t.on_complete:
                chain_info = f"\n  链式: {t.on_complete[:60]}{'…' if len(t.on_complete) > 60 else ''}"

            lines.append(
                f"[{t.status.value}] {t.name}\n"
                f"  id: {t.id}\n"
                f"  触发: {trigger_desc}\n"
                f"  配置: {t.config_profile}  投递: {t.delivery.value}"
                f"{retry_info}{chain_info}"
            )
        return "\n".join(lines)
