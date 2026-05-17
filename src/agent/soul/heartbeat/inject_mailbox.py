from __future__ import annotations

import threading

_GLOBAL: "HeartbeatInjectMailbox | None" = None
_GLOBAL_LOCK = threading.Lock()


class HeartbeatInjectMailbox:
    """Thread-safe slot consumed by :class:`TaoLoop` on the next user question (step 0)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: str | None = None

    def offer(self, text: str) -> None:
        t = text.strip()
        if not t:
            return
        with self._lock:
            self._pending = t

    def take_for_prompt(self) -> str | None:
        with self._lock:
            p = self._pending
            self._pending = None
            return p


def set_global_mailbox(m: HeartbeatInjectMailbox | None) -> None:
    with _GLOBAL_LOCK:
        global _GLOBAL
        _GLOBAL = m


def get_heartbeat_mailbox() -> HeartbeatInjectMailbox | None:
    with _GLOBAL_LOCK:
        return _GLOBAL
