from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from ..types import SessionOpenResult, SessionOpenTrigger
from .bootstrap import SessionBootstrap

if TYPE_CHECKING:
    from agent.soul.presence.service import PresenceService


class SessionStarter:
    """启动会话：sleep 唤醒 → 物理 idle 检查 → 按触发源初始化 dialogue。"""

    def __init__(
        self,
        bootstrap: SessionBootstrap,
        *,
        presence: PresenceService | None = None,
        on_rotate: Callable[[str], None] | None = None,
    ) -> None:
        self._bootstrap = bootstrap
        self._presence = presence
        self._on_rotate = on_rotate or (lambda _sid: None)

    def open(
        self,
        session_id: str,
        *,
        trigger: SessionOpenTrigger = "user_message",
        proactive_message: str = "",
        proactive_intent_id: str = "",
    ) -> SessionOpenResult:
        notes: list[str] = []
        woke = False
        if self._presence is not None and not self._presence.is_awake(session_id):
            self._presence.wake_up(session_id)
            woke = True
            notes.append("session: woke from sleep")

        before = self._bootstrap.registry.get(session_id)
        record, temporal_rotated = self._bootstrap.registry.ensure_active(session_id)
        if temporal_rotated:
            notes.extend(self._bootstrap.on_temporal_rotate(session_id))
            self._on_rotate(session_id)

        started, start_notes = self._bootstrap.ensure_dialogue_started(
            session_id,
            record,
            before_generation=before.generation,
            trigger=trigger,
        )
        notes.extend(start_notes)

        proactive_opened = False
        if trigger == "proactive_outbound":
            lifecycle = self._bootstrap.registry.lifecycle
            message = proactive_message.strip()
            if lifecycle is not None and message:
                lifecycle.open_proactive_outbound(
                    session_id,
                    message,
                    proactive_intent_id=proactive_intent_id,
                )
                proactive_opened = True
                notes.append("session: proactive outbound opened")

        return SessionOpenResult(
            session_id=session_id,
            generation=record.generation,
            trigger=trigger,
            woke=woke,
            temporal_rotated=temporal_rotated,
            started=started,
            proactive_opened=proactive_opened,
            notes=notes,
        )
