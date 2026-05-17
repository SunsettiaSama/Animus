from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class HeartbeatProtocol(Protocol):
    """心跳子系统协议。

    由 agent.heartbeat.HeartbeatModule 实现；
    TemporalClock / SchedulerEngine 仅依赖本 Protocol，不导入 agent 包。

    pending_force   — True 时 Clock 在下次 tick 中立即执行心跳（替代原私有 _force_tick）。
    tick()          — 执行一次心跳周期（同步，在线程池里调用）。
    force_tick()    — 请求立即执行一次心跳。
    read_file()     — 读取 HEARTBEAT.md 内容。
    write_file()    — 覆盖 HEARTBEAT.md。
    recent_log()    — 返回最近 n 条 tick 日志。
    """

    @property
    def pending_force(self) -> bool:
        ...

    def tick(self) -> Any:
        ...

    def force_tick(self) -> None:
        ...

    def read_file(self) -> str:
        ...

    def write_file(self, content: str) -> None:
        ...

    def recent_log(self, n: int = 50) -> list[dict]:
        ...
