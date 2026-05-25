from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .fsm.state import PresenceState
from .share_desire import ShareDesire
from .transition import PresenceInteraction


_PRESENCE_STATE_FILENAME = "presence_state.json"


@dataclass
class StoredPresenceSession:
    state: PresenceState
    interaction: PresenceInteraction
    awake: bool = False
    last_wake_date: str = ""


class PresenceStateStore:
    """按 session 持久化当下态 FSM、交互态与清醒标记。"""

    def __init__(self, life_dir: str) -> None:
        self._path = Path(life_dir) / _PRESENCE_STATE_FILENAME

    @classmethod
    def _load_session_payload(cls, payload: dict) -> StoredPresenceSession:
        if "state" in payload:
            state = PresenceState.from_dict(payload.get("state") or {})
            interaction = PresenceInteraction.from_dict(payload.get("interaction") or {})
            return StoredPresenceSession(
                state=state,
                interaction=interaction,
                awake=bool(payload.get("awake", False)),
                last_wake_date=str(payload.get("last_wake_date", "")),
            )

        state = PresenceState.from_dict(payload)
        interaction = PresenceInteraction()
        behavior = payload.get("behavior") or {}
        if behavior:
            interaction = PresenceInteraction.from_dict(behavior)
        motivation = payload.get("motivation") or {}
        share_desire = motivation.get("share_desire")
        if share_desire:
            interaction.share_desire = ShareDesire(str(share_desire))
        return StoredPresenceSession(
            state=state,
            interaction=interaction,
            awake=bool(payload.get("awake", False)),
            last_wake_date=str(payload.get("last_wake_date", "")),
        )

    def load_sessions(self) -> dict[str, StoredPresenceSession]:
        if not self._path.exists():
            return {}
        with open(self._path, encoding="utf-8") as f:
            raw = json.load(f)
        sessions = raw.get("sessions") or {}
        return {
            sid: self._load_session_payload(payload)
            for sid, payload in sessions.items()
        }

    def save_sessions(self, sessions: dict[str, StoredPresenceSession]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "sessions": {
                sid: {
                    "state": session.state.to_dict(),
                    "interaction": session.interaction.to_dict(),
                    "awake": session.awake,
                    "last_wake_date": session.last_wake_date,
                }
                for sid, session in sessions.items()
            }
        }
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
