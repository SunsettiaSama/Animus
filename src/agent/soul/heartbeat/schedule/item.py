from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class ChecklistTrigger(str, Enum):
    interval = "interval"
    daily = "daily"
    monthly = "monthly"


@dataclass
class ChecklistItem:
    """心跳待办时间轴上的一条注册项（wake registration 契约载体）。

    契约要点：``target`` 显式携带调用目标（"包.模块:函数" / "soul:方法" /
    可调用对象），heartbeat 只按契约调用，不含模块实现知识；
    ``domain`` / ``action`` 仅作标识与日志。
    """

    id: str
    domain: str
    action: str
    target: Callable[[dict, Any], Any] | str | None = None
    trigger: ChecklistTrigger = ChecklistTrigger.interval
    interval_sec: float = 300.0
    daily_at: str = "00:00"
    monthly_day: int = 0
    monthly_at: str = "00:00"
    payload: dict[str, Any] = field(default_factory=dict)
    heavy: bool = False                       # 重任务入 SoulEvolutionWorker
    run_outside_active_hours: bool = False    # 活跃时段外仍执行（如 memory-sleep）
    avoid_when_speaking: bool = False         # soul 说话中避让（声明式策略）
    enabled: bool = True
    last_run_mono: float = 0.0
    last_run_date: str = ""
    last_run_month: str = ""
