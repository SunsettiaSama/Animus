from __future__ import annotations

from typing import Protocol, runtime_checkable, TYPE_CHECKING

if TYPE_CHECKING:
    from runtime.scheduler.task import ScheduledTask
    from runtime.scheduler.store import TaskStore


@runtime_checkable
class TaskExecutorProtocol(Protocol):
    """执行层协议：接收一个 ScheduledTask，负责执行并更新 TaskStore 状态。

    由 agent.heartbeat.task_runner.TaskRunner 实现；
    TemporalClock / SchedulerEngine 仅依赖本 Protocol，不导入 agent 包。
    """

    async def run(self, task: "ScheduledTask", store: "TaskStore") -> None:
        ...
