from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ChecklistTrigger(str, Enum):
    interval = "interval"
    daily = "daily"
    monthly = "monthly"


@dataclass
class ChecklistItem:
    """心跳待办时间轴上的一条编排项。"""

    id: str
    domain: str
    action: str
    trigger: ChecklistTrigger = ChecklistTrigger.interval
    interval_sec: float = 300.0
    daily_at: str = "00:00"
    monthly_day: int = 0
    monthly_at: str = "00:00"
    payload: dict[str, Any] = field(default_factory=dict)
    channel: str = "api"
    enabled: bool = True
    last_run_mono: float = 0.0
    last_run_date: str = ""
    last_run_month: str = ""
