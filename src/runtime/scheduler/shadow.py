from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Literal

from runtime.scheduler.store import TaskStore
from runtime.scheduler.task import ScheduledTask


@dataclass
class ShadowChange:
    """One pending edit in the shadow buffer."""

    op: Literal["add", "edit", "cancel"]
    task_id: str
    fields: dict = field(default_factory=dict)
    task: ScheduledTask | None = None

    def to_dict(self) -> dict:
        return {
            "op": self.op,
            "task_id": self.task_id,
            "fields": self.fields,
            "task": self.task.to_dict() if self.task else None,
        }


class ShadowStore:
    """Draft-based editor for the live TaskStore.

    All mutation operations work on an in-memory buffer.  Nothing touches the
    live store until ``commit()`` is called.  ``discard()`` wipes the buffer.

    thread-safe: a single lock guards all reads and writes to ``_changes``.
    """

    _SHADOW_PREFIX = "shadow:"

    def __init__(self, live: TaskStore) -> None:
        self._live = live
        self._changes: list[ShadowChange] = []
        self._lock = threading.Lock()

    # ── Staging ───────────────────────────────────────────────────────────────

    def stage_add(self, task: ScheduledTask) -> str:
        """Buffer an 'add' operation; returns a shadow-scoped task_id."""
        shadow_id = self._SHADOW_PREFIX + str(uuid.uuid4())
        with self._lock:
            self._changes.append(ShadowChange(op="add", task_id=shadow_id, task=task))
        return shadow_id

    def stage_edit(self, task_id: str, **fields) -> None:
        """Buffer field updates for a live or shadow task."""
        with self._lock:
            # Merge into an existing shadow 'edit' for the same task_id if present
            for ch in self._changes:
                if ch.op == "edit" and ch.task_id == task_id:
                    ch.fields.update(fields)
                    return
            self._changes.append(ShadowChange(op="edit", task_id=task_id, fields=dict(fields)))

    def stage_cancel(self, task_id: str) -> None:
        """Buffer a cancel for a live or shadow task."""
        with self._lock:
            # Remove previous edits/adds for this task_id from the buffer
            self._changes = [
                ch for ch in self._changes
                if not (ch.task_id == task_id and ch.op in ("add", "edit"))
            ]
            self._changes.append(ShadowChange(op="cancel", task_id=task_id))

    # ── Preview ───────────────────────────────────────────────────────────────

    def preview(self) -> list[ScheduledTask]:
        """Compute and return the merged task list without committing."""
        with self._lock:
            changes = list(self._changes)

        tasks: dict[str, ScheduledTask] = {t.id: t for t in self._live.list_all()}
        cancelled_ids: set[str] = set()

        for ch in changes:
            if ch.op == "add" and ch.task is not None:
                tasks[ch.task_id] = ch.task
            elif ch.op == "edit":
                if ch.task_id in tasks:
                    raw = tasks[ch.task_id].to_dict()
                    raw.update(ch.fields)
                    tasks[ch.task_id] = ScheduledTask.from_dict(raw)
            elif ch.op == "cancel":
                cancelled_ids.add(ch.task_id)

        return [t for tid, t in tasks.items() if tid not in cancelled_ids]

    def list_staged(self) -> list[ShadowChange]:
        with self._lock:
            return list(self._changes)

    # ── Commit / Discard ──────────────────────────────────────────────────────

    def commit(self) -> int:
        """Apply buffered changes to the live TaskStore. Returns the number of applied changes."""
        with self._lock:
            changes = list(self._changes)
            self._changes.clear()

        applied = 0
        for ch in changes:
            if ch.op == "add" and ch.task is not None:
                # strip shadow prefix; assign a real uuid
                real = ScheduledTask.from_dict(ch.task.to_dict())
                real.id = str(uuid.uuid4())
                self._live.add(real)
                applied += 1
            elif ch.op == "edit":
                self._live.update(ch.task_id, **ch.fields)
                applied += 1
            elif ch.op == "cancel":
                self._live.cancel(ch.task_id)
                applied += 1
        return applied

    def discard(self) -> None:
        with self._lock:
            self._changes.clear()
