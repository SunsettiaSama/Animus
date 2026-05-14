from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from agent.flow.document import PlanDocument, PlanParser, PlanParseError
from agent.flow.patch import HumanPatch, PlanDiff, PatchOp

if TYPE_CHECKING:
    pass


class HumanEditChannel:
    def __init__(
        self,
        plan_dir: str,
        plan_id: str,
        poll_interval: float = 1.5,
        file_lock: asyncio.Lock | None = None,
    ) -> None:
        self._plan_dir = plan_dir
        self._plan_id = plan_id
        self._poll_interval = poll_interval
        self._shadow_path = Path(plan_dir) / f"{plan_id}.shadow.md"
        self._last_mtime: float = 0.0
        # Prefer the shared plan-dir-level lock when injected; fall back to own lock.
        self._write_lock = file_lock if file_lock is not None else asyncio.Lock()

        self.patch_queue: asyncio.Queue[HumanPatch] = asyncio.Queue()

    # ── Write shadow copy ─────────────────────────────────────────────────────

    def materialize(self, doc: PlanDocument) -> None:
        Path(self._plan_dir).mkdir(parents=True, exist_ok=True)
        self._shadow_path.write_text(doc.to_markdown(), encoding="utf-8")
        self._last_mtime = self._shadow_path.stat().st_mtime

    async def materialize_async(self, doc: PlanDocument) -> None:
        async with self._write_lock:
            async with doc._lock:
                text = doc.to_markdown()
            Path(self._plan_dir).mkdir(parents=True, exist_ok=True)
            self._shadow_path.write_text(text, encoding="utf-8")
            self._last_mtime = self._shadow_path.stat().st_mtime

    # ── Diff (sync, called inside watch) ─────────────────────────────────────

    def sync(self, live_doc: PlanDocument) -> list[HumanPatch]:
        if not self._shadow_path.exists():
            return []
        text = self._shadow_path.read_text(encoding="utf-8")
        try:
            edited = PlanParser.parse(text, strict=False)
        except PlanParseError:
            return []
        return PlanDiff.compute(live_doc, edited)

    # ── Background watcher ────────────────────────────────────────────────────

    async def watch(self, live_doc: PlanDocument) -> None:
        while True:
            await asyncio.sleep(self._poll_interval)
            if not self._shadow_path.exists():
                continue
            mtime = self._shadow_path.stat().st_mtime
            if mtime <= self._last_mtime:
                continue
            self._last_mtime = mtime

            patches = self.sync(live_doc)
            for patch in patches:
                if patch.op == PatchOp.pause:
                    live_doc.pause()
                elif patch.op == PatchOp.resume:
                    live_doc.resume()
                else:
                    await self.patch_queue.put(patch)

    # ── Drain pending patches ─────────────────────────────────────────────────

    async def drain(self) -> list[HumanPatch]:
        patches: list[HumanPatch] = []
        while not self.patch_queue.empty():
            patches.append(self.patch_queue.get_nowait())
        return patches

    # ── Apply patches to live doc ─────────────────────────────────────────────

    def apply(self, doc: PlanDocument, patches: list[HumanPatch]) -> list:
        return PlanDiff.apply(doc, patches)
