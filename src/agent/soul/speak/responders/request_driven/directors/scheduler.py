from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..orchestrator.state import StateStore


class PollScheduler:
    """帧过程调度：append + idle；间隔 t 与是否执行由帧数管理器双层抽样。"""

    def __init__(self, state_store: StateStore) -> None:
        self._state_store = state_store

    def arm(self, session_id: str, trigger: str) -> None:
        frame_mgr = self._state_store.poll_frame_manager(session_id, trigger)
        frame_mgr.armed = True
        if frame_mgr.next_fire_at <= 0:
            frame_mgr.schedule_next()

    def disarm(self, session_id: str, trigger: str) -> None:
        frame_mgr = self._state_store.poll_frame_manager(session_id, trigger)
        frame_mgr.armed = False

    def clear_session(self, session_id: str) -> None:
        state = self._state_store.session(session_id)
        for frame_mgr in state.poll_frame_managers.values():
            frame_mgr.reset()

    def due_triggers(self, session_id: str, *, now: float | None = None) -> list[str]:
        current = now if now is not None else time.monotonic()
        state = self._state_store.session(session_id)
        due: list[str] = []
        for key, frame_mgr in state.poll_frame_managers.items():
            if frame_mgr.is_session_expired():
                continue
            if not frame_mgr.armed:
                continue
            if frame_mgr.next_fire_at > 0 and current >= frame_mgr.next_fire_at:
                decision = frame_mgr.take_due_frame(now=current)
                if decision.execute:
                    due.append(key)
        return due
