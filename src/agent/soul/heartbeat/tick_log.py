from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from config.storage import StorageConfig


@dataclass
class HeartbeatTickResult:
    outcome: str
    reason:  str  = ""
    duration_ms: int = 0
    detail_for_inject: str = ""


class HeartbeatTickLog:
    def __init__(self, scheduler_dir: str) -> None:
        scheduler_dir = StorageConfig().resolve_scheduler_dir(scheduler_dir)
        self._path = os.path.join(scheduler_dir, "heartbeat_log.jsonl")
        self._lock = threading.Lock()
        os.makedirs(scheduler_dir, exist_ok=True)

    def append(self, result: HeartbeatTickResult) -> None:
        entry = {
            "ts":          datetime.now(timezone.utc).isoformat(),
            "outcome":     result.outcome,
            "reason":      result.reason,
            "duration_ms": result.duration_ms,
        }
        if result.detail_for_inject:
            entry["detail_for_inject"] = result.detail_for_inject[:8000]
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def recent(self, n: int = 50) -> list[dict]:
        with self._lock:
            if not os.path.exists(self._path):
                return []
            with open(self._path, encoding="utf-8") as f:
                lines = f.readlines()
        result = []
        for line in reversed(lines[-n * 2:]):
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            result.append(entry)
            if len(result) >= n:
                break
        return result
