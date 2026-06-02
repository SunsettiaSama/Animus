from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.speak.io.inbound.compose.render import render_presence_fuel_for_agent

if TYPE_CHECKING:
    from agent.soul.speak.io.inbound.compose.store import SpeakStatusStore


def collect_state_portrait(
    *,
    presence_snap,
    max_presence_chars: int = 350,
    status_store: SpeakStatusStore | None = None,
) -> str:
    """从 presence 读取近期状态人格（第二人称述）。"""
    session_id = getattr(presence_snap, "session_id", "tao")
    presence = ""
    if status_store is not None:
        presence = status_store.presence(session_id).strip()
    if not presence:
        presence = render_presence_fuel_for_agent(
            presence_snap.state,
            max_chars=max_presence_chars,
        )
    return presence.strip()
