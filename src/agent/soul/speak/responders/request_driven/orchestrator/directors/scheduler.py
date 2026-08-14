from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..state import StateStore


class PollScheduler:
    """sqrt(2) 条件轮询器：append + idle 两类 trigger。"""

    def __init__(self, state_store: StateStore) -> None:
        self._state_store = state_store

    def arm(self, session_id: str, trigger: str) -> None:
        cursor = self._state_store.poll_cursor(session_id, trigger)
        cursor.armed = True
        if cursor.next_fire_at <= 0:
            cursor.schedule_next()

    def disarm(self, session_id: str, trigger: str) -> None:
        cursor = self._state_store.poll_cursor(session_id, trigger)
        cursor.armed = False

    def clear_session(self, session_id: str) -> None:
        state = self._state_store.session(session_id)
        for cursor in state.poll_cursors.values():
            cursor.reset()

    def due_triggers(self, session_id: str, *, now: float | None = None) -> list[str]:
        current = now if now is not None else time.monotonic()
        state = self._state_store.session(session_id)
        due: list[str] = []
        for key, cursor in state.poll_cursors.items():
            if cursor.is_session_expired():
                continue
            if not cursor.armed:
                continue
            if cursor.next_fire_at > 0 and current >= cursor.next_fire_at:
                due.append(key)
        return due
