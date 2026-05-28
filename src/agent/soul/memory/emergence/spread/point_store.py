from __future__ import annotations

import threading
import time

from agent.soul.memory.emergence.types import PointEmergenceResult


def _store_key(session_id: str, turn_index: int) -> str:
    return f"{session_id}:{turn_index}"


class PointEmergenceStore:
    def __init__(self, *, ttl_sec: float = 300.0) -> None:
        self._ttl = ttl_sec
        self._lock = threading.Lock()
        self._data: dict[str, tuple[PointEmergenceResult, float]] = {}

    def put(self, result: PointEmergenceResult) -> None:
        key = _store_key(result.session_id, result.turn_index)
        with self._lock:
            self._data[key] = (result, time.monotonic())

    def get(self, session_id: str, turn_index: int) -> PointEmergenceResult | None:
        key = _store_key(session_id, turn_index)
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            result, ts = item
            if time.monotonic() - ts > self._ttl:
                del self._data[key]
                return None
            return result

    def get_latest(self, session_id: str) -> PointEmergenceResult | None:
        with self._lock:
            prefix = f"{session_id}:"
            candidates: list[tuple[int, PointEmergenceResult, float]] = []
            for key, (result, ts) in self._data.items():
                if not key.startswith(prefix):
                    continue
                if time.monotonic() - ts > self._ttl:
                    continue
                candidates.append((result.turn_index, result, ts))
            if not candidates:
                return None
            candidates.sort(key=lambda item: item[0], reverse=True)
            return candidates[0][1]
