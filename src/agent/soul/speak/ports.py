from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .drive import SpeakDriveResult, SpeakDriveSnapshot
    from .unit import SpeakAnswer, SpeakExchange


class SpeakInboundPort(Protocol):
    """接收外界话语（用户 → Soul）。"""

    def on_user_text(self, session_id: str, text: str) -> SpeakExchange: ...


class SpeakOutboundPort(Protocol):
    """向外界说话（Soul → 用户）。"""

    def deliver(
        self,
        session_id: str,
        text: str,
        *,
        final: bool = True,
    ) -> SpeakAnswer: ...


class SpeakDrivePort(Protocol):
    """当下态内驱读口：从 presence 状态机读取冲动与分享意愿。"""

    def drive_snapshot(self, session_id: str) -> SpeakDriveSnapshot: ...

    def evaluate_drive(self, session_id: str) -> SpeakDriveResult: ...
