from __future__ import annotations

from collections.abc import Callable

from agent.soul.speak.compose.bundle import SpeakPromptBundle
from agent.soul.speak.compose.interactor_portrait import render_interactor_portrait_inject
from agent.soul.speak.compose.memory import render_similar_memories_block
from agent.soul.speak.session.prompt_trace import get_prompt_trace

from .gateway import InboundMemoryGateway
from .request import (
    InteractorPortraitPullResult,
    InteractorPortraitRequest,
    PointQueryRequest,
    SimilarMemoryPullResult,
)

GetBoundInteractor = Callable[[str], str]


class InboundMemoryComposeBridge:
    """Memory 检索结果入站：异步预取 + 有限等待，写入 ``SpeakPromptBundle``。"""

    def __init__(
        self,
        gateway: InboundMemoryGateway,
        *,
        get_bound_interactor: GetBoundInteractor,
        compose_wait_ms: int = 100,
    ) -> None:
        self._gateway = gateway
        self._get_bound_interactor = get_bound_interactor
        self._compose_wait_ms = max(0, compose_wait_ms)

    @property
    def gateway(self) -> InboundMemoryGateway:
        return self._gateway

    def attach_ports(
        self,
        *,
        recall_fn=None,
        point_query_fn=None,
        pull_similar_fn=None,
        portrait_query_fn=None,
        pull_portrait_fn=None,
    ) -> None:
        if recall_fn is not None:
            self._gateway.attach_recall(recall_fn)
        if point_query_fn is not None:
            self._gateway.attach_point_query(point_query_fn)
        if pull_similar_fn is not None:
            self._gateway.attach_pull_similar(pull_similar_fn)
        if portrait_query_fn is not None:
            self._gateway.attach_portrait_query(portrait_query_fn)
        if pull_portrait_fn is not None:
            self._gateway.attach_pull_portrait(pull_portrait_fn)

    def request_similar_memories(
        self,
        session_id: str,
        *,
        turn_index: int,
        user_text: str,
        agent_text: str = "",
    ) -> None:
        self._gateway.request_point_query(
            PointQueryRequest(
                session_id=session_id,
                interactor_id=self._get_bound_interactor(session_id),
                turn_index=turn_index,
                user_text=user_text,
                agent_text=agent_text,
            ),
        )

    def pull_similar_memories(
        self,
        session_id: str,
        turn_index: int,
    ) -> SimilarMemoryPullResult:
        return self._gateway.pull_similar_memories(
            session_id,
            turn_index,
            wait_ms=self._compose_wait_ms,
        )

    def apply_similar_memories(
        self,
        bundle: SpeakPromptBundle,
        pulled: SimilarMemoryPullResult,
    ) -> None:
        inject_block = render_similar_memories_block(pulled.inject.lines)
        if inject_block:
            bundle.injected.status.similar_memories = inject_block
        if pulled.inject.unit_ids:
            bundle.meta.setdefault("activated_memory_ids", [])
            bundle.meta["activated_memory_ids"].extend(pulled.inject.unit_ids)
        if pulled.spilled.lines or pulled.spilled.unit_ids:
            bundle.meta["memory_spill"] = {
                "turn_index": pulled.spilled.turn_index,
                "lines": list(pulled.spilled.lines),
                "unit_ids": list(pulled.spilled.unit_ids),
            }
        if get_prompt_trace().is_enabled(bundle.session_id):
            trace_pull = bundle.meta.setdefault("trace_pull", {})
            if isinstance(trace_pull, dict):
                trace_pull["memory"] = {
                    "inject_lines": list(pulled.inject.lines),
                    "inject_unit_ids": list(pulled.inject.unit_ids),
                    "inject_turn_index": pulled.inject.turn_index,
                    "spill_lines": list(pulled.spilled.lines),
                    "spill_unit_ids": list(pulled.spilled.unit_ids),
                    "spill_turn_index": pulled.spilled.turn_index,
                }

    def request_interactor_portrait(
        self,
        session_id: str,
        *,
        turn_index: int,
        user_text: str,
        agent_text: str = "",
    ) -> None:
        self._gateway.request_interactor_portrait(
            InteractorPortraitRequest(
                session_id=session_id,
                turn_index=turn_index,
                user_text=user_text,
                agent_text=agent_text,
                hinted_interactor_id=self._get_bound_interactor(session_id),
            ),
        )

    def pull_interactor_portrait(
        self,
        session_id: str,
        turn_index: int,
    ) -> InteractorPortraitPullResult:
        return self._gateway.pull_interactor_portrait(
            session_id,
            turn_index,
            wait_ms=self._compose_wait_ms,
        )

    def apply_interactor_portrait(
        self,
        bundle: SpeakPromptBundle,
        pulled: InteractorPortraitPullResult,
    ) -> None:
        block = render_interactor_portrait_inject(pulled.portrait_text)
        if block:
            bundle.injected.status.interactor_portrait = block
        if pulled.interactor_id:
            bundle.meta["resolved_interactor_id"] = pulled.interactor_id
        if pulled.turn_index:
            bundle.meta["interactor_portrait_turn_index"] = pulled.turn_index
        if get_prompt_trace().is_enabled(bundle.session_id):
            trace_pull = bundle.meta.setdefault("trace_pull", {})
            if isinstance(trace_pull, dict):
                trace_pull["portrait"] = {
                    "portrait_text": pulled.portrait_text,
                    "interactor_id": pulled.interactor_id,
                    "turn_index": pulled.turn_index,
                }

    def refresh_similar_memories_after_turn(
        self,
        session_id: str,
        *,
        turn_index: int,
        user_text: str,
        agent_text: str,
    ) -> None:
        if not user_text.strip() and not agent_text.strip():
            return
        self.request_similar_memories(
            session_id,
            turn_index=turn_index,
            user_text=user_text,
            agent_text=agent_text,
        )

    def refresh_interactor_portrait_on_bundle(
        self,
        session_id: str,
        bundle: SpeakPromptBundle,
        turn_index: int,
    ) -> None:
        pulled = self.pull_interactor_portrait(session_id, turn_index)
        if pulled.portrait_text.strip():
            self.apply_interactor_portrait(bundle, pulled)

    def pull_compose_context(
        self,
        session_id: str,
        *,
        user_text: str,
        turn_index: int,
    ) -> tuple[SimilarMemoryPullResult, InteractorPortraitPullResult]:
        self.request_similar_memories(
            session_id,
            turn_index=turn_index,
            user_text=user_text,
        )
        self.request_interactor_portrait(
            session_id,
            turn_index=turn_index,
            user_text=user_text,
        )
        return (
            self.pull_similar_memories(session_id, turn_index),
            self.pull_interactor_portrait(session_id, turn_index),
        )

    def apply_compose_context(
        self,
        bundle: SpeakPromptBundle,
        *,
        similar: SimilarMemoryPullResult,
        portrait: InteractorPortraitPullResult,
    ) -> None:
        self.apply_similar_memories(bundle, similar)
        self.apply_interactor_portrait(bundle, portrait)
