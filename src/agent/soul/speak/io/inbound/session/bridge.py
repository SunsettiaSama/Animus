from __future__ import annotations

from typing import TYPE_CHECKING

from ....session.service import SpeakSessionService

SpeakSessionManager = SpeakSessionService

if TYPE_CHECKING:
    from agent.soul.speak.service import SpeakService


class SpeakSessionBridge:
    """inbound ↔ session 通信桥：委托 SpeakSessionManager。"""

    def __init__(
        self,
        service: SpeakService,
        *,
        manager: SpeakSessionService | None = None,
    ) -> None:
        self._service = service
        self._manager = manager or service.session_manager

    @property
    def manager(self) -> SpeakSessionService:
        return self._manager

    @property
    def registry(self):
        return self._manager.registry

    def ensure_active(self, session_id: str):
        record, _rotated = self._manager.registry.ensure_active(session_id)
        return record

    def touch(self, session_id: str):
        return self._manager.registry.touch(session_id)

    def open(self, session_id: str):
        return self._manager.open(session_id)

    def dispatch_turn(self, chunk, *, record_fn, reset_context, on_after=None):
        _ = reset_context
        return self._manager.record_turn(chunk, on_after=on_after)
