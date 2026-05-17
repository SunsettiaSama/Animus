from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .event import EventType, LifeEvent  # noqa: F401 (re-exported)

_FILENAME = "life_events.jsonl"
_RETENTION_DAYS = 365


class LifeEventLog:
    """事实账本——只追加，不修改，不衰减。

    职责
    ----
    记录"发生了什么"的客观事实，是全系统事实的权威来源。
    memory 层的 FactualMemory 通过 life_event_id 关联回这里。
    status 层通过 LifeContextInput 读取这里的数据。

    设计约束
    --------
    - append-only：写入后不允许修改，只能追加
    - 不做情感解读，description 必须是事实陈述
    - 留存时间远长于记忆（默认 365 天）
    """

    def __init__(self, life_dir: str, retention_days: int = _RETENTION_DAYS) -> None:
        self._path = Path(life_dir) / _FILENAME
        self._retention_days = retention_days

    def append(self, event: LifeEvent) -> LifeEvent:
        """追加一条事件，返回写入的事件（携带已设定的 id）。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        return event

    def recent(
        self,
        days: int = 7,
        event_types: list[EventType] | None = None,
    ) -> list[LifeEvent]:
        """读取最近 N 天内的事件，可按类型过滤。"""
        if not self._path.exists():
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        events: list[LifeEvent] = []
        with open(self._path, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                d = json.loads(raw)
                ts_str = d.get("ts", "")
                if not ts_str:
                    continue
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    continue
                event = LifeEvent.from_dict(d)
                if event_types and event.event_type not in event_types:
                    continue
                events.append(event)
        return events

    def since(self, dt: datetime) -> list[LifeEvent]:
        """读取某时间点之后的所有事件。"""
        if not self._path.exists():
            return []
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        events: list[LifeEvent] = []
        with open(self._path, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                d = json.loads(raw)
                ts_str = d.get("ts", "")
                if not ts_str:
                    continue
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= dt:
                    events.append(LifeEvent.from_dict(d))
        return events

    def get_by_id(self, event_id: str) -> LifeEvent | None:
        """按 id 查找特定事件（用于 FactualMemory 关联查询）。"""
        if not self._path.exists():
            return None
        with open(self._path, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                d = json.loads(raw)
                if d.get("id") == event_id:
                    return LifeEvent.from_dict(d)
        return None

    def purge_old(self) -> None:
        if not self._path.exists():
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=self._retention_days)
        kept: list[str] = []
        with open(self._path, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                d = json.loads(raw)
                ts_str = d.get("ts", "")
                if not ts_str:
                    kept.append(raw)
                    continue
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    kept.append(raw)
        with open(self._path, "w", encoding="utf-8") as f:
            for line in kept:
                f.write(line + "\n")
