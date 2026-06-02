from __future__ import annotations

from dataclasses import dataclass, field

from .state import GuidanceControlState, GuidanceSessionRecord


@dataclass
class GuidanceControlStore:
    _sessions: dict[str, GuidanceSessionRecord] = field(default_factory=dict)

    def record(self, session_id: str) -> GuidanceSessionRecord:
        sid = session_id.strip()
        if not sid:
            raise ValueError("session_id 不能为空")
        if sid not in self._sessions:
            self._sessions[sid] = GuidanceSessionRecord()
        return self._sessions[sid]

    def get(self, session_id: str) -> GuidanceControlState | None:
        sid = session_id.strip()
        if not sid:
            return None
        entry = self._sessions.get(sid)
        if entry is None or entry.current is None:
            return None
        if entry.current.remaining_turns < 1:
            return None
        return entry.current

    def clear(self, session_id: str) -> None:
        sid = session_id.strip()
        if sid:
            self._sessions.pop(sid, None)
