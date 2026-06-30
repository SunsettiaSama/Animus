from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config.soul.presence.config import EXPERIENCE_HOT_WINDOW_HOURS

from agent.soul.life.experience.domain.unit import ExperienceUnit

_FILENAME = "experience_hot.jsonl"


class ExperienceLog:
    """体验热存储——以本地 JSONL 缓存为唯一事实源（非进程内内存）。

    append-only 写入 ``life_dir/<filename>``，窗口外由 ``purge_old`` 清仓。
    交会折叠时从文件中物理移除被 supersede 的参与单元，仅保留 collision unit。
    """

    def __init__(
        self,
        life_dir: str,
        window_hours: int = EXPERIENCE_HOT_WINDOW_HOURS,
        *,
        filename: str = _FILENAME,
    ) -> None:
        self._path = Path(life_dir) / filename
        self._window_hours = window_hours

    def append(self, unit: ExperienceUnit) -> ExperienceUnit:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(unit.to_dict(), ensure_ascii=False) + "\n")
        return unit

    def remove_by_ids(self, unit_ids: set[str]) -> int:
        """从热存储中删除指定体验单元（交会折叠 supersede 参与方）。"""
        if not unit_ids or not self._path.exists():
            return 0
        kept: list[str] = []
        removed = 0
        with open(self._path, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                d = json.loads(raw)
                if d.get("id") in unit_ids:
                    removed += 1
                    continue
                kept.append(raw)
        if removed:
            with open(self._path, "w", encoding="utf-8") as f:
                for line in kept:
                    f.write(line + "\n")
        return removed

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

    def upsert(self, unit: ExperienceUnit) -> ExperienceUnit:
        if not self._path.exists():
            return self.append(unit)
        kept: list[str] = []
        replaced = False
        with open(self._path, encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                d = json.loads(raw)
                if d.get("id") == unit.id:
                    kept.append(json.dumps(unit.to_dict(), ensure_ascii=False))
                    replaced = True
                else:
                    kept.append(raw)
        if not replaced:
            kept.append(json.dumps(unit.to_dict(), ensure_ascii=False))
        with open(self._path, "w", encoding="utf-8") as f:
            for line in kept:
                f.write(line + "\n")
        return unit
