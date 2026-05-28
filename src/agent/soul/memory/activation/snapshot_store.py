from __future__ import annotations

import hashlib
import threading
import time

from agent.soul.memory.domain import ActivationSnapshot


class ActivationSnapshotStore:
    def __init__(self, *, ttl_sec: float = 300.0) -> None:
        self._ttl = ttl_sec
        self._lock = threading.Lock()
        self._data: dict[str, tuple[ActivationSnapshot, float]] = {}

    def put(self, snapshot: ActivationSnapshot) -> None:
        with self._lock:
            self._data[snapshot.session_id] = (snapshot, time.monotonic())

    def get(self, session_id: str) -> ActivationSnapshot | None:
        with self._lock:
            item = self._data.get(session_id)
            if item is None:
                return None
            snapshot, ts = item
            if time.monotonic() - ts > self._ttl:
                del self._data[session_id]
                return None
            return snapshot


def cue_hash(session_id: str, user_text: str, agent_text: str, interactor_id: str) -> str:
    raw = f"{session_id}|{interactor_id}|{user_text}|{agent_text}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
