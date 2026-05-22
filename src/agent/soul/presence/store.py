from __future__ import annotations

import json
from pathlib import Path

from .fsm.state import PresenceState


_PRESENCE_STATE_FILENAME = "presence_state.json"


class PresenceStateStore:
    """按 session 持久化 当下态 FSM（含 affect 附属字段）。"""

    def __init__(self, life_dir: str) -> None:
        self._path = Path(life_dir) / _PRESENCE_STATE_FILENAME

    def load_sessions(self) -> dict[str, PresenceState]:
        if not self._path.exists():
            return {}
        with open(self._path, encoding="utf-8") as f:
            raw = json.load(f)
        sessions = raw.get("sessions") or {}
        return {
            sid: PresenceState.from_dict(state)
            for sid, state in sessions.items()
        }

    def save_sessions(self, sessions: dict[str, PresenceState]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "sessions": {
                sid: state.to_dict()
                for sid, state in sessions.items()
            }
        }
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
