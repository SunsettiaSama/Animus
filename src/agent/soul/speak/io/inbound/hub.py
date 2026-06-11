from __future__ import annotations

from collections.abc import Callable

from ...orchestrator.runner import SpeakComposeRunner
from ...session import SpeakSessionService
from ...session.lifecycle import SpeakSessionRegistry
from .compose.gateway import InboundComposeGateway
from .compose.request import ComposePrepareRequest
from .drive import SpeakDriveBridge
from .memory import InboundMemoryGateway
from .memory.compose_bridge import InboundMemoryComposeBridge


class SpeakInboundHub:
    """Speak 入站总线（主路径已接线）。

    - ``memory`` + ``memory_compose``：涌现 / 关键字 / 画像与 compose 注入
    - ``compose``：Presence 推送 → 状态缓存 → ``SpeakComposeRunner`` 预组装
    - ``drive``：presence 冲动 / 分享意愿
    - ``registry``：``SpeakSessionRegistry``（interactor 绑定、轮次）
    - Life 记账在 ``io.outbound.life``，**非**本 hub
    """

    def __init__(
        self,
        *,
        compose_runner: SpeakComposeRunner,
        session_manager: SpeakSessionService,
        share_threshold: float | None = None,
        presence=None,
        on_compose_prepare: Callable[[ComposePrepareRequest], None] | None = None,
        keyword_wait_ms: int = 200,
        memory_budget: int = 5,
        portrait_wait_ms: int = 100,
    ) -> None:
        self._registry = session_manager.registry
        self.memory = InboundMemoryGateway()
        self.memory_compose = InboundMemoryComposeBridge(
            self.memory,
            get_bound_interactor=self._registry.get_bound_interactor,
            keyword_wait_ms=keyword_wait_ms,
            memory_budget=memory_budget,
            portrait_wait_ms=portrait_wait_ms,
            recall_pick_weights=session_manager.queues.memory_queue,
        )
        self.compose = InboundComposeGateway(compose_runner)
        self.drive = SpeakDriveBridge(presence, share_threshold=share_threshold)
        if on_compose_prepare is not None:
            self.compose.attach_scheduler(on_compose_prepare)

    def attach_memory_ports(
        self,
        *,
        recall_fn=None,
        point_query_fn=None,
        keyword_query_fn=None,
        pull_similar_fn=None,
        portrait_query_fn=None,
        pull_portrait_fn=None,
    ) -> None:
        self.memory_compose.attach_ports(
            recall_fn=recall_fn,
            point_query_fn=point_query_fn,
            keyword_query_fn=keyword_query_fn,
            pull_similar_fn=pull_similar_fn,
            portrait_query_fn=portrait_query_fn,
            pull_portrait_fn=pull_portrait_fn,
        )

    @property
    def registry(self) -> SpeakSessionRegistry:
        return self._registry

    def bind_interactor(self, session_id: str, interactor_id: str) -> None:
        self._registry.bind_interactor(session_id, interactor_id)

    def attach_presence(self, bridge) -> None:
        self.presence = bridge
