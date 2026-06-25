from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import DirectorPlan


class DirectorPlanStore:
    def __init__(self) -> None:
        self._plans: dict[tuple[str, int], DirectorPlan] = {}
        self._generation: dict[str, int] = {}
        self._lock = threading.Lock()

    def generation(self, session_id: str) -> int:
        sid = session_id.strip()
        with self._lock:
            return self._generation.get(sid, 0)

    def bump_generation(self, session_id: str) -> int:
        sid = session_id.strip()
        with self._lock:
            next_gen = self._generation.get(sid, 0) + 1
            self._generation[sid] = next_gen
            keys = [key for key in self._plans if key[0] == sid]
            for key in keys:
                self._plans.pop(key, None)
            return next_gen

    def save(self, plan: DirectorPlan) -> None:
        sid = plan.session_id.strip()
        key = (sid, plan.target_turn_index)
        with self._lock:
            self._plans[key] = plan

    def load(self, session_id: str, turn_index: int) -> DirectorPlan | None:
        sid = session_id.strip()
        key = (sid, turn_index)
        with self._lock:
            plan = self._plans.get(key)
            if plan is None:
                return None
            if plan.generation != self._generation.get(sid, 0):
                return None
            return plan

    def clear_session(self, session_id: str) -> None:
        sid = session_id.strip()
        with self._lock:
            self._generation.pop(sid, None)
            keys = [key for key in self._plans if key[0] == sid]
            for key in keys:
                self._plans.pop(key, None)
