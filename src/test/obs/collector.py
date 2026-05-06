from __future__ import annotations

import dataclasses
import json
import threading
import time
from contextvars import ContextVar
from datetime import date
from pathlib import Path

_session_id_var: ContextVar[str] = ContextVar("obs_session_id", default="")


class ObsCollector:
    """Thread-safe JSONL writer for observability events.

    One JSONL file is created per day: `.react/logs/obs_YYYY-MM-DD.jsonl`.
    Each line is a JSON object with a ``kind`` field identifying the event type.
    """

    def __init__(self, log_dir: Path) -> None:
        self._log_dir = log_dir
        self._lock = threading.Lock()

    def _log_path(self) -> Path:
        return self._log_dir / f"obs_{date.today().isoformat()}.jsonl"

    def emit(self, event: object) -> None:
        d = dataclasses.asdict(event)  # type: ignore[arg-type]
        d["kind"] = type(event).__name__
        line = json.dumps(d, ensure_ascii=False)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            with open(self._log_path(), "a", encoding="utf-8") as fh:
                fh.write(line + "\n")

    def set_session(self, sid: str) -> None:
        _session_id_var.set(sid)

    def current_session(self) -> str:
        return _session_id_var.get()

    def read_today(self) -> list[dict]:
        p = self._log_path()
        if not p.exists():
            return []
        result: list[dict] = []
        for raw in p.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if raw:
                result.append(json.loads(raw))
        return result

    def read_session(self, session_id: str) -> list[dict]:
        return [e for e in self.read_today() if e.get("session_id") == session_id]


_collector: ObsCollector | None = None


def get_collector() -> ObsCollector:
    global _collector
    if _collector is None:
        from config import paths
        _collector = ObsCollector(paths.cache_root / "logs")
    return _collector
