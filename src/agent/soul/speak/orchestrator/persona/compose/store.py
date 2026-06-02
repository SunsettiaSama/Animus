from __future__ import annotations

from dataclasses import dataclass, field

from .state import PersonaComposeState, PersonaSessionRecord


@dataclass
class PersonaComposeStore:
    _sessions: dict[str, PersonaSessionRecord] = field(default_factory=dict)

    def record(self, session_id: str) -> PersonaSessionRecord:
        sid = session_id.strip()
        if not sid:
            raise ValueError("session_id 不能为空")
        if sid not in self._sessions:
            self._sessions[sid] = PersonaSessionRecord()
        return self._sessions[sid]

    def get(self, session_id: str) -> PersonaComposeState | None:
        sid = session_id.strip()
        if not sid:
            return None
        entry = self._sessions.get(sid)
        if entry is None or entry.current is None:
            return None
        return entry.current

    def clear(self, session_id: str) -> None:
        sid = session_id.strip()
        if sid:
            self._sessions.pop(sid, None)
