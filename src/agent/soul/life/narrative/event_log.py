from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .event import NarrativeEvent

_FILENAME = "narrative_events.jsonl"
_RETENTION_DAYS = 365


class NarrativeEventLog:
    """叙事事件日志（单文件 append-only）。"""

    def __init__(self, life_dir: str, retention_days: int = _RETENTION_DAYS) -> None:
        self._path = Path(life_dir) / _FILENAME
        self._retention_days = retention_days

    def append(self, event: NarrativeEvent) -> NarrativeEvent:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        return event

    def recent(
        self,
        days: int = 7,
        kinds: list | None = None,
    ) -> list[NarrativeEvent]:
        if not self._path.exists():
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        out: list[NarrativeEvent] = []
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
                ev = NarrativeEvent.from_dict(d)
                if kinds is not None and ev.kind not in kinds:
                    continue
                out.append(ev)
        return out

    def since(self, dt: datetime) -> list[NarrativeEvent]:
        if not self._path.exists():
            return []
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        out: list[NarrativeEvent] = []
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
                    out.append(NarrativeEvent.from_dict(d))
        return out

    def get_by_id(self, event_id: str) -> NarrativeEvent | None:
        if not self._path.exists():
            return None
        with open(self._path, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                d = json.loads(raw)
                if d.get("id") == event_id:
                    return NarrativeEvent.from_dict(d)
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
