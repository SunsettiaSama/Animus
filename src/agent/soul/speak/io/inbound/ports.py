from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .unit import SpeakExchange


class SpeakInboundPort(Protocol):
    """接收外界话语（用户 → Soul）。"""

    def on_user_text(self, session_id: str, text: str) -> SpeakExchange: ...
