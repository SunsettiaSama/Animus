from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path


class InactivityDeadline:
    def __init__(
        self,
        timeout_sec: float,
        *,
        on_timeout: Callable[[], None],
    ) -> None:
        if timeout_sec <= 0:
            raise ValueError("inactivity timeout must be positive")
        self._timeout_sec = timeout_sec
        self._on_timeout = on_timeout
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        self.reset()

    def reset(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            timer = threading.Timer(self._timeout_sec, self._on_timeout)
            timer.daemon = True
            timer.start()
            self._timer = timer

    def stop(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


def hard_exit_on_timeout(output_dir: Path, timeout_sec: float) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    marker = {
        "reason": "no_completed_case_before_deadline",
        "timeout_sec": timeout_sec,
        "terminated_at": time.time(),
        "exit_code": 124,
    }
    (output_dir / "deadline.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os._exit(124)
