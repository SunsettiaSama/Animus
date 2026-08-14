"""Thread-safe persistent store for Worker portraits."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from worker.state.schema import (
    AGENT_STATE_SCHEMA_VERSION,
    MEMORY_PORTRAIT_SLOT,
    REFLECTION_PORTRAIT_SLOT,
    WORKER_PORTRAIT_SLOT,
    AgentStateSnapshot,
    MemoryPortraitState,
    ReflectionPortraitState,
    StateSlot,
    WorkerPortraitState,
    utc_now_iso,
)

_STATE_FILENAME = "agent_state.json"


class AgentStateStore:
    """Owns the global Agent State document for the main Worker agent."""

    def __init__(self, state_dir: str | Path) -> None:
        self._dir = Path(state_dir)
        self._path = self._dir / _STATE_FILENAME
        self._lock = threading.RLock()
        self._worker_portrait = WorkerPortraitState()
        self._reflection_portrait = ReflectionPortraitState()
        self._memory_portrait = MemoryPortraitState.empty()
        self.load()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> None:
        with self._lock:
            if not self._path.is_file():
                self._worker_portrait = WorkerPortraitState()
                self._reflection_portrait = ReflectionPortraitState()
                self._memory_portrait = MemoryPortraitState.empty()
                return
            text = self._path.read_text(encoding="utf-8").strip()
            if not text:
                raise ValueError(f"agent_state.json must not be empty: {self._path}")
            data = json.loads(text)
            if not isinstance(data, dict):
                raise ValueError(f"agent_state.json root must be object: {self._path}")
            version = str(data.get("schema_version", ""))
            if version != AGENT_STATE_SCHEMA_VERSION:
                raise ValueError(f"unsupported agent state schema: {version!r}")
            slots = data.get("slots") or {}
            if not isinstance(slots, dict):
                raise ValueError(f"agent_state.json slots must be object: {self._path}")
            worker_raw = slots.get(WORKER_PORTRAIT_SLOT)
            reflection_raw = slots.get(REFLECTION_PORTRAIT_SLOT)
            memory_raw = slots.get(MEMORY_PORTRAIT_SLOT)
            if not isinstance(worker_raw, dict) or not isinstance(reflection_raw, dict):
                raise ValueError("agent_state.json requires both portrait slots")
            self._worker_portrait = WorkerPortraitState.from_dict(worker_raw)
            self._reflection_portrait = ReflectionPortraitState.from_dict(
                reflection_raw
            )
            self._memory_portrait = (
                MemoryPortraitState.from_dict(memory_raw)
                if isinstance(memory_raw, dict)
                else MemoryPortraitState.empty()
            )

    def save(self) -> None:
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema_version": AGENT_STATE_SCHEMA_VERSION,
                "updated_at": utc_now_iso(),
                "slots": {
                    WORKER_PORTRAIT_SLOT: self._worker_portrait.to_dict(),
                    REFLECTION_PORTRAIT_SLOT: self._reflection_portrait.to_dict(),
                    MEMORY_PORTRAIT_SLOT: self._memory_portrait.to_dict(),
                },
            }
            temp_path = self._path.with_suffix(".tmp")
            temp_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temp_path.replace(self._path)

    def read(self, slot_type: str) -> StateSlot | None:
        with self._lock:
            if slot_type == WORKER_PORTRAIT_SLOT:
                return self._worker_portrait
            if slot_type == REFLECTION_PORTRAIT_SLOT:
                return self._reflection_portrait
            if slot_type == MEMORY_PORTRAIT_SLOT:
                return self._memory_portrait
            return None

    def snapshot(self) -> AgentStateSnapshot:
        with self._lock:
            return AgentStateSnapshot.from_slots(
                worker_portrait=self._worker_portrait,
                reflection_portrait=self._reflection_portrait,
                memory_portrait=self._memory_portrait,
                captured_at=utc_now_iso(),
            )

    def commit(self, slot: StateSlot) -> None:
        with self._lock:
            if slot.slot_type == WORKER_PORTRAIT_SLOT:
                if not isinstance(slot, WorkerPortraitState):
                    raise TypeError("worker_portrait requires WorkerPortraitState")
                self._worker_portrait = slot
            elif slot.slot_type == REFLECTION_PORTRAIT_SLOT:
                if not isinstance(slot, ReflectionPortraitState):
                    raise TypeError(
                        "reflection_portrait requires ReflectionPortraitState"
                    )
                self._reflection_portrait = slot
            elif slot.slot_type == MEMORY_PORTRAIT_SLOT:
                if not isinstance(slot, MemoryPortraitState):
                    raise TypeError("memory_portrait requires MemoryPortraitState")
                self._memory_portrait = slot
            else:
                raise ValueError(f"unknown slot_type: {slot.slot_type!r}")
            self.save()

    def clear(self) -> None:
        with self._lock:
            self._worker_portrait = WorkerPortraitState()
            self._reflection_portrait = ReflectionPortraitState()
            self._memory_portrait = MemoryPortraitState.empty()
            if self._path.is_file():
                self._path.unlink()
