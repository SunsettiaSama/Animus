from __future__ import annotations

from collections.abc import Callable

from agent.soul.memory.emergence.types import PointEmergenceResult
from agent.soul.memory.facade.interactor_portrait import InteractorPortraitSpeakResult

from .channel import SessionMemoryChannel
from .deps import SessionIODeps
from .outbound.dynamic_event import schedule_dynamic_event
from .outbound.dynamic_portrait import run_dynamic_portrait
from .outbound.static_portrait import load_static_core_portrait
from .request import (
    CompressionBlockAck,
    CompressionBlockInbound,
    DialogueTurnInbound,
    SessionCloseAck,
    SessionCloseInbound,
    StaticPortraitInbound,
)


class SessionSpeakIO:
    """Memory ↔ Speak 会话级双向 I/O（``SoulService._ensure_speak_service`` 接线）。

    注意命名：与 ``agent.posture``、``speak/session``（Speak 队列/生命周期）不是同一模块。

    入站：
    - 对话轮 → 动态画像 / 动态事件（emergence）
    - 账号绑定 → 静态 SocialCore 画像
    - 压缩块 / 会话闭合 → SessionMemoryBuffer

    出站（进程内回调 → Speak ``InboundMemoryGateway`` / session 队列 pull）：
    - 静态 / 动态画像 ``InteractorPortraitSpeakResult``
    - 点事件 ``PointEmergenceResult``
    """

    def __init__(
        self,
        *,
        compression: SessionMemoryChannel,
        deps: SessionIODeps,
    ) -> None:
        self._compression = compression
        self._deps = deps
        self._on_static_portrait: Callable[[InteractorPortraitSpeakResult], None] | None = None
        self._on_dynamic_portrait: Callable[[InteractorPortraitSpeakResult], None] | None = None
        self._on_dynamic_event: Callable[[PointEmergenceResult], None] | None = None
        deps.emergence.spread.on_point_ready(self._dispatch_dynamic_event)

    @property
    def compression(self) -> SessionMemoryChannel:
        return self._compression

    @property
    def deps(self) -> SessionIODeps:
        return self._deps

    def on_static_portrait_ready(
        self,
        handler: Callable[[InteractorPortraitSpeakResult], None] | None,
    ) -> None:
        self._on_static_portrait = handler

    def on_dynamic_portrait_ready(
        self,
        handler: Callable[[InteractorPortraitSpeakResult], None] | None,
    ) -> None:
        self._on_dynamic_portrait = handler

    def on_dynamic_event_ready(
        self,
        handler: Callable[[PointEmergenceResult], None] | None,
    ) -> None:
        self._on_dynamic_event = handler

    def _dispatch_dynamic_event(self, result: PointEmergenceResult) -> None:
        if self._on_dynamic_event is not None:
            self._on_dynamic_event(result)

    def _emit_static_portrait(self, payload: InteractorPortraitSpeakResult) -> None:
        if self._on_static_portrait is not None:
            self._on_static_portrait(payload)

    def _emit_dynamic_portrait(self, payload: InteractorPortraitSpeakResult) -> None:
        if self._on_dynamic_portrait is not None:
            self._on_dynamic_portrait(payload)

    def submit_dialogue_turn(self, inbound: DialogueTurnInbound) -> None:
        """Speak 投递一轮对话；按标志异步触发动态画像 / 事件检索。"""
        if inbound.want_dynamic_portrait:
            self._deps.enqueue_write(
                lambda: self._emit_dynamic_portrait(
                    run_dynamic_portrait(self._deps, inbound)
                )
            )
        if inbound.want_dynamic_event:
            schedule_dynamic_event(self._deps, inbound)

    def fetch_static_portrait(self, inbound: StaticPortraitInbound) -> None:
        """账号 interactor 就绪后异步拉取 core 画像并出站。"""
        def _task() -> None:
            payload = load_static_core_portrait(
                self._deps,
                interactor_id=inbound.interactor_id,
                session_id=inbound.session_id,
                turn_index=inbound.turn_index,
            )
            self._emit_static_portrait(payload)

        self._deps.enqueue_write(_task)

    def ingest_compression_block(self, request: CompressionBlockInbound) -> CompressionBlockAck:
        return self._compression.ingest_compression_block(request)

    def close_session(self, request: SessionCloseInbound) -> SessionCloseAck:
        return self._compression.close_session(request)
