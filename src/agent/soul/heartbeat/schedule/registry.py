from __future__ import annotations

import logging
from datetime import datetime

from .item import ChecklistItem

logger = logging.getLogger(__name__)


class ChecklistRegistry:
    """注册表：项由各模块经 wiring 注册（register/register_all），
    heartbeat 不内置任何域的默认清单。"""

    def __init__(
        self,
        items: list[ChecklistItem] | None = None,
        *,
        cfg=None,
    ) -> None:
        self._items: dict[str, ChecklistItem] = {}
        self.register_all(items or [])

    def register(self, item: ChecklistItem) -> None:
        """注册一项；同 id 后者覆盖前者（告警）。target 必填。"""
        if not item.id:
            raise ValueError("ChecklistItem.id 不能为空")
        if item.target is None:
            raise ValueError(f"checklist 项 {item.id!r} 缺少 target（wake registration 契约）")
        if item.id in self._items:
            logger.warning("[ChecklistRegistry] 重复注册 %r，后者覆盖前者", item.id)
        self._items[item.id] = item

    def register_all(self, items: list[ChecklistItem]) -> None:
        for item in items:
            self.register(item)

    def all(self) -> list[ChecklistItem]:
        return list(self._items.values())

    def off_hours_items(self) -> list[ChecklistItem]:
        """活跃时段外仍需执行（run_outside_active_hours）的项。"""
        return [i for i in self._items.values() if i.run_outside_active_hours]

    def due(self, now_mono: float, now_dt: datetime) -> list[ChecklistItem]:
        due: list[ChecklistItem] = []
        today = now_dt.date().isoformat()
        for item in self._items.values():
            if not item.enabled:
                continue
            if item.trigger.value == "interval":
                if item.last_run_mono <= 0.0 or now_mono - item.last_run_mono >= item.interval_sec:
                    due.append(item)
            elif item.trigger.value == "daily":
                if item.last_run_date == today:
                    continue
                hh, mm = item.daily_at.split(":")
                if now_dt.hour > int(hh) or (now_dt.hour == int(hh) and now_dt.minute >= int(mm)):
                    due.append(item)
            elif item.trigger.value == "monthly":
                month_key = now_dt.strftime("%Y-%m")
                if item.last_run_month == month_key:
                    continue
                if now_dt.day < item.monthly_day:
                    continue
                hh, mm = item.monthly_at.split(":")
                if now_dt.hour > int(hh) or (now_dt.hour == int(hh) and now_dt.minute >= int(mm)):
                    due.append(item)
        return due

    def mark_run(self, item: ChecklistItem, now_mono: float, now_dt: datetime) -> None:
        item.last_run_mono = now_mono
        if item.trigger.value == "daily":
            item.last_run_date = now_dt.date().isoformat()
        if item.trigger.value == "monthly":
            item.last_run_month = now_dt.strftime("%Y-%m")
