from __future__ import annotations

import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _WindowState:
    last_user_at: datetime
    timer: threading.Timer | None = None


class ProactiveSessionWindowManager:
    """Tracks the user-opened Speak window for proactive follow-up timing."""

    def __init__(
        self,
        *,
        timeout_sec: float = 600.0,
        on_timeout: Callable[[str], None] | None = None,
        now_fn: Callable[[], datetime] | None = None,
    ) -> None:
        self.timeout_sec = max(1.0, float(timeout_sec))
        self._on_timeout = on_timeout
        self._now_fn = now_fn or _utcnow
        self._lock = threading.RLock()
        self._states: dict[str, _WindowState] = {}

    def touch_user_message(self, session_id: str) -> float:
        sid = session_id.strip()
        if not sid:
            return 0.0
        with self._lock:
            state = self._states.get(sid)
            if state is not None and state.timer is not None:
                state.timer.cancel()
            state = _WindowState(last_user_at=self._now_fn())
            state.timer = threading.Timer(self.timeout_sec, self._fire_timeout, args=(sid,))
            state.timer.daemon = True
            state.timer.start()
            self._states[sid] = state
            return 1.0

    def set_timeout_handler(self, handler: Callable[[str], None] | None) -> None:
        self._on_timeout = handler

    def decay(self, session_id: str) -> float:
        sid = session_id.strip()
        if not sid:
            return 0.0
        with self._lock:
            state = self._states.get(sid)
            if state is None:
                return 0.0
            elapsed = max(0.0, (self._now_fn() - state.last_user_at).total_seconds())
            return 1.0 / math.sqrt(1.0 + elapsed / self.timeout_sec)

    def clear_session(self, session_id: str) -> None:
        sid = session_id.strip()
        if not sid:
            return
        with self._lock:
            state = self._states.pop(sid, None)
            if state is not None and state.timer is not None:
                state.timer.cancel()

    def clear_all(self) -> None:
        with self._lock:
            states = list(self._states.values())
            self._states.clear()
        for state in states:
            if state.timer is not None:
                state.timer.cancel()

    def _fire_timeout(self, session_id: str) -> None:
        should_timeout = False
        with self._lock:
            state = self._states.get(session_id)
            if state is None:
                return
            elapsed = max(0.0, (self._now_fn() - state.last_user_at).total_seconds())
            if elapsed >= self.timeout_sec:
                self._states.pop(session_id, None)
                should_timeout = True
        if should_timeout and self._on_timeout is not None:
            self._on_timeout(session_id)
