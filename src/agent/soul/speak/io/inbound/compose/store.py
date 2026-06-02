from __future__ import annotations

from dataclasses import dataclass

from .render import render_presence_fuel_for_agent


@dataclass
class _SessionStatus:
    presence: str = ""


class SpeakStatusStore:
    """按 session 缓存 speak 状态层字段（由 inbound 接收 presence 推送）。"""

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionStatus] = {}

    def update_presence(self, session_id: str, presence: str) -> None:
        self._session(session_id).presence = presence.strip()

    def presence(self, session_id: str) -> str:
        return self._session(session_id).presence

    def reset_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def _session(self, session_id: str) -> _SessionStatus:
        if session_id not in self._sessions:
            self._sessions[session_id] = _SessionStatus()
        return self._sessions[session_id]


def apply_presence_status_update(
    store: SpeakStatusStore,
    snap,
    *,
    max_presence_chars: int = 350,
) -> None:
    """将 presence 近期经历燃料写入 inbound 状态层缓存。"""
    session_id = getattr(snap, "session_id", "tao")
    store.update_presence(
        session_id,
        render_presence_fuel_for_agent(snap.state, max_chars=max_presence_chars),
    )
