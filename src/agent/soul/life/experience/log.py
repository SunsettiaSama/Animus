from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .unit import ExperienceUnit

_FILENAME = "experience_hot.jsonl"
_DEFAULT_WINDOW_HOURS = 2


class ExperienceLog:
    """时间窗口热存储——append-only JSONL，自然衰减，窗口外的体验由 purge_old 清仓。"""

    def __init__(self, life_dir: str, window_hours: int = _DEFAULT_WINDOW_HOURS) -> None:
        self._path = Path(life_dir) / _FILENAME
        self._window_hours = window_hours

    def append(self, unit: ExperienceUnit) -> ExperienceUnit:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(unit.to_dict(), ensure_ascii=False) + "\n")
        return unit

    def recent(self, hours: int | None = None) -> list[ExperienceUnit]:
        if not self._path.exists():
            return []
        window = hours if hours is not None else self._window_hours
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window)
        out: list[ExperienceUnit] = []
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
                    out.append(ExperienceUnit.from_dict(d))
        return out

    def purge_old(self, hours: int | None = None) -> None:
        if not self._path.exists():
            return
        window = hours if hours is not None else self._window_hours
        cutoff = datetime.now(timezone.utc) - timedelta(hours=window)
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

    def get_by_id(self, experience_id: str) -> ExperienceUnit | None:
        if not self._path.exists():
            return None
        with open(self._path, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                d = json.loads(raw)
                if d.get("id") == experience_id:
                    return ExperienceUnit.from_dict(d)
        return None
