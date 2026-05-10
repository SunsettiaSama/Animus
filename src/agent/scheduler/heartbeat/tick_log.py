from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone


@dataclass
class HeartbeatTickResult:
    outcome:     str   # "ok" | "escalate" | "skip" | "error"
    reason:      str   = ""
    duration_ms: int   = 0


class HeartbeatTickLog:
    """Append-only JSONL log of every heartbeat tick."""

    def __init__(self, scheduler_dir: str) -> None:
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
