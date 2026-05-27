from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .request import SpeakRequest
    from .unit import SpeakAnswer


class SpeakOutboundPort(Protocol):
    """向外界说话（Soul → 用户）。"""

    def deliver(
        self,
        session_id: str,
        text: str,
        *,
        final: bool = True,
    ) -> SpeakAnswer: ...


class SpeakOrchestratorPort(Protocol):
    """Speak 顶层编排口（含 proactive 出站）。"""

    def run_turn(
        self,
        session_id: str,
        user_text: str,
        *,
        stream: bool = False,
        mode: str = "inbound",
    ) -> dict: ...

    def handle_proactive(self, request: SpeakRequest) -> dict: ...
