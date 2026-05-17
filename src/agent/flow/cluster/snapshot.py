from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .document import PlanDocument, TaskStatus

if TYPE_CHECKING:
    pass

try:
    import aiofiles
    _AIOFILES = True
except ImportError:
    _AIOFILES = False


@dataclass
class PlanSnapshot:
    snapshot_id: str
    plan_id: str
    timestamp: float
    trigger: str
    cycle: int
    doc_dict: dict


class SnapshotStore:
    def __init__(
        self,
        plan_dir: str,
        plan_id: str,
        file_lock: asyncio.Lock | None = None,
    ) -> None:
        self._plan_id = plan_id
        self._dir = Path(plan_dir) / plan_id / "snapshots"
        self._dir.mkdir(parents=True, exist_ok=True)
        # Prefer the shared plan-dir-level lock when injected; fall back to own lock.
        self._write_lock = file_lock if file_lock is not None else asyncio.Lock()

    def _path(self, snapshot_id: str) -> Path:
        return self._dir / f"{snapshot_id}.json"

    # ── Sync save (used at plan init before async loop starts) ───────────────

    def save(self, doc: PlanDocument, trigger: str, cycle: int) -> PlanSnapshot:
        import time
        snapshot = PlanSnapshot(
            snapshot_id=str(uuid.uuid4()),
            plan_id=self._plan_id,
            timestamp=time.time(),
            trigger=trigger,
            cycle=cycle,
            doc_dict=doc.to_dict(),
        )
        self._path(snapshot.snapshot_id).write_text(
            json.dumps(snapshot.__dict__, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return snapshot

    # ── Async save (used during concurrent dispatch) ──────────────────────────

    async def save_async(self, doc: PlanDocument, trigger: str, cycle: int) -> PlanSnapshot:
        import time
        async with self._write_lock:
            async with doc._lock:
                doc_dict = doc.to_dict()
        snapshot = PlanSnapshot(
            snapshot_id=str(uuid.uuid4()),
            plan_id=self._plan_id,
            timestamp=time.time(),
            trigger=trigger,
            cycle=cycle,
            doc_dict=doc_dict,
        )
        data = json.dumps(snapshot.__dict__, ensure_ascii=False, indent=2, default=str)
        async with self._write_lock:
            if _AIOFILES:
                import aiofiles  # type: ignore
                async with aiofiles.open(self._path(snapshot.snapshot_id), "w", encoding="utf-8") as f:
                    await f.write(data)
            else:
                self._path(snapshot.snapshot_id).write_text(data, encoding="utf-8")
        return snapshot

    # ── List / load ───────────────────────────────────────────────────────────

    def list(self) -> list[PlanSnapshot]:
        snapshots: list[PlanSnapshot] = []
        for p in self._dir.glob("*.json"):
            raw = json.loads(p.read_text(encoding="utf-8"))
            snapshots.append(PlanSnapshot(**raw))
        return sorted(snapshots, key=lambda s: s.timestamp, reverse=True)

    def load(self, snapshot_id: str) -> PlanDocument:
        raw = json.loads(self._path(snapshot_id).read_text(encoding="utf-8"))
        snapshot = PlanSnapshot(**raw)
        return PlanDocument.from_dict(snapshot.doc_dict)

    def rollback(self, snapshot_id: str) -> PlanDocument:
        doc = self.load(snapshot_id)
        for task in doc.all_tasks():
            if task.status in (TaskStatus.running, TaskStatus.failed):
                task.status = TaskStatus.pending
                task.result = None
                task.error = None
                task.execution_ctx = None
        return doc
