from __future__ import annotations

from datetime import datetime, timezone

from config.soul.config import SoulConfig
from agent.soul.handlers.api.actions import LifeAction, MemoryAction, PersonaAction

from .item import ChecklistItem, ChecklistTrigger


def default_checklist(cfg: SoulConfig | None = None) -> list[ChecklistItem]:
    """内置待办时间轴：间隔与配额来自 ``SoulConfig``。"""
    c = cfg or SoulConfig.default()
    return [
        ChecklistItem(
            id="life-plan-landmark",
            domain="life",
            action=LifeAction.PLAN_LANDMARK,
            trigger=ChecklistTrigger.interval,
            interval_sec=c.landmark_write_interval_sec,
        ),
        ChecklistItem(
            id="life-trigger-landmark",
            domain="life",
            action=LifeAction.TRIGGER_LANDMARKS,
            trigger=ChecklistTrigger.interval,
            interval_sec=c.landmark_trigger_interval_sec,
        ),
        ChecklistItem(
            id="life-surprise",
            domain="life",
            action=LifeAction.TICK_SURPRISE,
            trigger=ChecklistTrigger.interval,
            interval_sec=c.surprise_tick_interval_sec,
            payload={"elapsed_sec": c.surprise_tick_interval_sec},
        ),
        ChecklistItem(
            id="life-scheduler-digest",
            domain="life",
            action=LifeAction.RECORD_SCHEDULER_DIGEST,
            trigger=ChecklistTrigger.interval,
            interval_sec=c.heartbeat_scan_interval_sec,
        ),
        ChecklistItem(
            id="memory-wander",
            domain="memory",
            action=MemoryAction.WANDER,
            trigger=ChecklistTrigger.interval,
            interval_sec=c.wander_interval_sec,
        ),
        ChecklistItem(
            id="memory-forget",
            domain="memory",
            action=MemoryAction.FORGET_SCAN,
            trigger=ChecklistTrigger.interval,
            interval_sec=c.memory_forget_interval_sec,
        ),
        ChecklistItem(
            id="drive-external-scan",
            domain="drive",
            action="scan_external_opportunity",
            trigger=ChecklistTrigger.interval,
            interval_sec=900.0,
            payload={"session_id": "tao"},
        ),
        ChecklistItem(
            id="persona-monthly-drift",
            domain="persona",
            action=PersonaAction.RUN_MONTHLY_DRIFT,
            trigger=ChecklistTrigger.monthly,
            monthly_day=c.persona_drift_day_of_month,
            monthly_at=c.persona_drift_at,
            enabled=True,
        ),
    ]


class ChecklistRegistry:
    def __init__(
        self,
        items: list[ChecklistItem] | None = None,
        *,
        cfg: SoulConfig | None = None,
    ) -> None:
        self._items: dict[str, ChecklistItem] = {}
        for item in items or default_checklist(cfg):
            self._items[item.id] = item

    def all(self) -> list[ChecklistItem]:
        return list(self._items.values())

    def due(self, now_mono: float, now_dt: datetime) -> list[ChecklistItem]:
        due: list[ChecklistItem] = []
        today = now_dt.date().isoformat()
        for item in self._items.values():
            if not item.enabled:
                continue
            if item.trigger == ChecklistTrigger.interval:
                if item.last_run_mono <= 0.0 or now_mono - item.last_run_mono >= item.interval_sec:
                    due.append(item)
            elif item.trigger == ChecklistTrigger.daily:
                if item.last_run_date == today:
                    continue
                hh, mm = item.daily_at.split(":")
                if now_dt.hour > int(hh) or (now_dt.hour == int(hh) and now_dt.minute >= int(mm)):
                    due.append(item)
            elif item.trigger == ChecklistTrigger.monthly:
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
        if item.trigger == ChecklistTrigger.daily:
            item.last_run_date = now_dt.date().isoformat()
        if item.trigger == ChecklistTrigger.monthly:
            item.last_run_month = now_dt.strftime("%Y-%m")
