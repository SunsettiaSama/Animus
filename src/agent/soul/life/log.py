from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

_FILENAME = "life_log.jsonl"
_RETENTION_DAYS = 90


@dataclass
class LifeLogEntry:
    ts: str
    period_start: str
    period_end: str
    narrative: str
    source_tasks: list[str] = field(default_factory=list)
    entry_type: str = "scheduler_activity"  # scheduler_activity | thought | creative | scheduler_action

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "narrative": self.narrative,
            "source_tasks": self.source_tasks,
            "type": self.entry_type,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LifeLogEntry:
        return cls(
            ts=d.get("ts", ""),
            period_start=d.get("period_start", ""),
            period_end=d.get("period_end", ""),
            narrative=d.get("narrative", ""),
            source_tasks=d.get("source_tasks", []),
            entry_type=d.get("type", "scheduler_activity"),
        )


class LifeLog:
    def __init__(self, life_dir: str, retention_days: int = _RETENTION_DAYS) -> None:
        self._path = Path(life_dir) / _FILENAME
        self._retention_days = retention_days

    def append(self, entry: LifeLogEntry) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")

    def recent(self, days: int = 30) -> list[LifeLogEntry]:
        if not self._path.exists():
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        entries: list[LifeLogEntry] = []
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
                if ts >= cutoff:
                    entries.append(LifeLogEntry.from_dict(d))
        return entries

    def last_entry_ts(self) -> datetime | None:
        if not self._path.exists():
            return None
        last_ts: datetime | None = None
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
                last_ts = ts
        return last_ts

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
