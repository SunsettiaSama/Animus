from __future__ import annotations

from typing import TYPE_CHECKING

from .block import SpeakStatusInjected
from .render import render_presence_fuel_for_agent

if TYPE_CHECKING:
    from .store import SpeakStatusStore


def collect_status_injected(
    *,
    presence_snap,
    dialogue_compressed: str = "",
    max_presence_chars: int = 350,
    status_store: SpeakStatusStore | None = None,
) -> SpeakStatusInjected:
    """从 presence / 会话上下文采集状态层，供 compose 注入。"""
    session_id = getattr(presence_snap, "session_id", "tao")
    presence = ""
    if status_store is not None:
        presence = status_store.presence(session_id)
    if not presence:
        presence = render_presence_fuel_for_agent(
            presence_snap.state,
            max_chars=max_presence_chars,
        )
    return SpeakStatusInjected(
        presence=presence,
        dialogue_compressed=dialogue_compressed.strip(),
    )
