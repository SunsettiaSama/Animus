from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from agent.soul.memory.emergence.types import PointEmergenceResult
from agent.soul.memory.facade.interactor_portrait import InteractorPortraitSpeakResult

from .request import (
    CompressionBlockAck,
    CompressionBlockInbound,
    DialogueTurnInbound,
    SessionCloseAck,
    SessionCloseInbound,
    StaticPortraitInbound,
)


class SessionSpeakInboundPort(Protocol):
    """Speak → Memory（经 Soul 转发）。"""

    def submit_dialogue_turn(self, inbound: DialogueTurnInbound) -> None: ...

    def fetch_static_portrait(self, inbound: StaticPortraitInbound) -> None: ...

    def ingest_compression_block(self, request: CompressionBlockInbound) -> CompressionBlockAck: ...

    def close_session(self, request: SessionCloseInbound) -> SessionCloseAck: ...


class SessionSpeakOutboundPort(Protocol):
    """Memory → Speak（异步回调，Soul 注册后转发给 Speak 队列）。"""

    def on_static_portrait_ready(
        self,
        handler: Callable[[InteractorPortraitSpeakResult], None] | None,
    ) -> None: ...

    def on_dynamic_portrait_ready(
        self,
        handler: Callable[[InteractorPortraitSpeakResult], None] | None,
    ) -> None: ...

    def on_dynamic_event_ready(
        self,
        handler: Callable[[PointEmergenceResult], None] | None,
    ) -> None: ...
