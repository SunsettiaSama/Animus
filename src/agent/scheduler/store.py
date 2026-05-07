from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

from agent.scheduler.task import ScheduledTask, TaskStatus


class TaskStore:
    def __init__(self, scheduler_dir: str):
        self._dir = scheduler_dir
        self._tasks_path = os.path.join(scheduler_dir, "tasks.json")
        self._lock = threading.Lock()
        os.makedirs(scheduler_dir, exist_ok=True)
        os.makedirs(os.path.join(scheduler_dir, "results"), exist_ok=True)

    # ── Read ──────────────────────────────────────────────────────────────────

    def _load(self) -> dict[str, dict]:
        if not os.path.exists(self._tasks_path):
            return {}
        with open(self._tasks_path, encoding="utf-8") as f:
            return json.load(f)

    def _save(self, data: dict[str, dict]) -> None:
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

    def reset_stale_running(self) -> int:
        """将遗留的 running 状态任务重置为 pending（服务重启后调用）。"""
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
                t = datetime.fromisoformat(next_run.replace("Z", "+00:00"))
                if t.tzinfo is None:
                    t = t.replace(tzinfo=timezone.utc)
                if t <= now_utc:
                    due.append(ScheduledTask.from_dict(raw))
            except ValueError:
                continue
        return due
