from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone

from config.storage import StorageConfig

from runtime.scheduler.task import ScheduledTask, TaskStatus

logger = logging.getLogger(__name__)


def _parse_utc(iso: str) -> datetime:
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t


class TaskStore:
    def __init__(self, scheduler_dir: str):
        scheduler_dir = StorageConfig().resolve_scheduler_dir(scheduler_dir)
        self._dir = scheduler_dir
        self._tasks_path = os.path.join(scheduler_dir, "tasks.json")
        self._lock = threading.Lock()
        self._cache: dict[str, dict] | None = None
        os.makedirs(scheduler_dir, exist_ok=True)
        os.makedirs(os.path.join(scheduler_dir, "results"), exist_ok=True)

    # ── Read/Write with in-memory cache ──────────────────────────────────────

    def _load(self) -> dict[str, dict]:
        if self._cache is not None:
            return self._cache
        if not os.path.exists(self._tasks_path):
            self._cache = {}
            return self._cache
        with open(self._tasks_path, encoding="utf-8") as f:
            self._cache = json.load(f)
        return self._cache

    def _save(self, data: dict[str, dict]) -> None:
        self._cache = data
        with open(self._tasks_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ── Public API ────────────────────────────────────────────────────────────

    def add(self, task: ScheduledTask) -> None:
        with self._lock:
            data = self._load()
            data[task.id] = task.to_dict()
            self._save(data)

    def get(self, task_id: str) -> ScheduledTask | None:
        with self._lock:
            data = self._load()
        raw = data.get(task_id)
        return ScheduledTask.from_dict(raw) if raw else None

    def list_all(self) -> list[ScheduledTask]:
        with self._lock:
            data = self._load()
        return [ScheduledTask.from_dict(v) for v in data.values()]

    def update(self, task_id: str, **kwargs) -> None:
        with self._lock:
            data = self._load()
            if task_id not in data:
                return
            for k, v in kwargs.items():
                if k == "status" and isinstance(v, TaskStatus):
                    data[task_id][k] = v.value
                else:
                    data[task_id][k] = v
            self._save(data)

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            data = self._load()
            if task_id not in data:
                return False
            data[task_id]["status"] = TaskStatus.cancelled.value
            self._save(data)
        return True

    def pause(self, task_id: str) -> bool:
        with self._lock:
            data = self._load()
            if task_id not in data:
                return False
            if data[task_id].get("status") not in (TaskStatus.pending.value,):
                return False
            data[task_id]["status"] = TaskStatus.paused.value
            self._save(data)
        return True

    def resume(self, task_id: str) -> bool:
        with self._lock:
            data = self._load()
            if task_id not in data:
                return False
            if data[task_id].get("status") != TaskStatus.paused.value:
                return False
            data[task_id]["status"] = TaskStatus.pending.value
            self._save(data)
        return True

    def reset_stale_running(self) -> int:
        with self._lock:
            data = self._load()
            count = 0
            for raw in data.values():
                if raw.get("status") == TaskStatus.running.value:
                    raw["status"] = TaskStatus.pending.value
                    count += 1
            if count:
                self._save(data)
        return count

    def get_due_tasks(self, now: datetime) -> list[ScheduledTask]:
        with self._lock:
            data = self._load()
        now_utc = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
        due: list[ScheduledTask] = []
        for raw in data.values():
            if raw.get("status") != TaskStatus.pending.value:
                continue
            next_run = raw.get("next_run_at")
            if not next_run:
                continue
            try:
                t = _parse_utc(next_run)
                if t <= now_utc:
                    due.append(ScheduledTask.from_dict(raw))
            except ValueError:
                continue
        return due

    def advance_cron(self, task_id: str) -> str | None:
        with self._lock:
            data = self._load()
            raw = data.get(task_id)
            if raw is None:
                return None
            cron_expr = raw.get("trigger", {}).get("cron_expr")
            if not cron_expr:
                return None
            now = datetime.now(timezone.utc)
            next_dt = _next_cron(cron_expr, now)
            if next_dt is None:
                return None
            raw["next_run_at"] = next_dt.isoformat()
            raw["status"] = TaskStatus.pending.value
            self._save(data)
        return next_dt.isoformat()

    def cleanup_old_tasks(self, retention_days: int) -> int:
        if retention_days <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        terminal = {TaskStatus.done.value, TaskStatus.cancelled.value}
        with self._lock:
            data = self._load()
            remove_ids = []
            for tid, raw in data.items():
                if raw.get("status") not in terminal:
                    continue
                updated_at = raw.get("updated_at") or raw.get("next_run_at") or ""
                if not updated_at:
                    continue
                try:
                    ts = _parse_utc(updated_at)
                    if ts < cutoff:
                        remove_ids.append(tid)
                except ValueError:
                    continue
            for tid in remove_ids:
                del data[tid]
            if remove_ids:
                self._save(data)
                logger.info(
                    "[TaskStore] cleanup removed %d old tasks (retention=%d days)",
                    len(remove_ids), retention_days,
                )
        return len(remove_ids)


def _next_cron(expr: str, after: datetime) -> datetime | None:
    try:
        from croniter import croniter
        it = croniter(expr, after)
        return it.get_next(datetime).replace(tzinfo=timezone.utc)
    except Exception as exc:
        logger.warning("[TaskStore] cron calculation failed for %r: %s", expr, exc)
        return None
