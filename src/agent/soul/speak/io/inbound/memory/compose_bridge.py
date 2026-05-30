from __future__ import annotations

from collections.abc import Callable

from agent.soul.speak.compose.bundle import SpeakPromptBundle
from agent.soul.speak.compose.interactor_portrait import render_interactor_portrait_inject
from agent.soul.memory.emergence.line_dedup import dedupe_memory_line_pairs
from agent.soul.speak.compose.memory import render_similar_memories_block
from agent.soul.speak.session.prompt_trace import get_prompt_trace

from .gateway import InboundMemoryGateway
from .request import (
    InteractorPortraitPullResult,
    InteractorPortraitRequest,
    KeywordQueryRequest,
    PointQueryRequest,
    SimilarMemoryPullResult,
)

GetBoundInteractor = Callable[[str], str]


class InboundMemoryComposeBridge:
    """Memory 检索结果入站：双通道（关键字 + 涌现）与 compose 注入。"""

    def __init__(
        self,
        gateway: InboundMemoryGateway,
        *,
        get_bound_interactor: GetBoundInteractor,
        keyword_wait_ms: int = 200,
        memory_budget: int = 5,
        portrait_wait_ms: int = 100,
        merge_ratio: float | None = None,
    ) -> None:
        self._gateway = gateway
        self._get_bound_interactor = get_bound_interactor
        self._keyword_wait_ms = max(0, keyword_wait_ms)
        self._memory_budget = max(1, memory_budget)
        self._portrait_wait_ms = max(0, portrait_wait_ms)
        self._merge_ratio = merge_ratio

    @property
    def gateway(self) -> InboundMemoryGateway:
        return self._gateway

    def attach_ports(
        self,
        *,
        recall_fn=None,
        point_query_fn=None,
        keyword_query_fn=None,
        pull_similar_fn=None,
        portrait_query_fn=None,
        pull_portrait_fn=None,
    ) -> None:
        if recall_fn is not None:
            self._gateway.attach_recall(recall_fn)
        if point_query_fn is not None:
            self._gateway.attach_point_query(point_query_fn)
        if keyword_query_fn is not None:
            self._gateway.attach_keyword_query(keyword_query_fn)
        if pull_similar_fn is not None:
            self._gateway.attach_pull_similar(pull_similar_fn)
        if portrait_query_fn is not None:
            self._gateway.attach_portrait_query(portrait_query_fn)
        if pull_portrait_fn is not None:
            self._gateway.attach_pull_portrait(pull_portrait_fn)

    def request_emergence_query(
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

    def request_keyword_query(
        self,
        session_id: str,
        *,
        turn_index: int,
        user_text: str,
        agent_text: str = "",
    ) -> None:
        self._gateway.request_keyword_query(
            KeywordQueryRequest(
                session_id=session_id,
                interactor_id=self._get_bound_interactor(session_id),
                turn_index=turn_index,
                user_text=user_text,
                agent_text=agent_text,
            ),
        )

    def request_similar_memories(
        self,
        session_id: str,
        *,
        turn_index: int,
        user_text: str,
        agent_text: str = "",
    ) -> None:
        self.request_emergence_query(
            session_id,
            turn_index=turn_index,
            user_text=user_text,
            agent_text=agent_text,
        )

    def pull_similar_memories(
        self,
        session_id: str,
        turn_index: int,
    ) -> SimilarMemoryPullResult:
        return self._gateway.pull_similar_memories(
            session_id,
            turn_index,
            keyword_wait_ms=self._keyword_wait_ms,
            budget=self._memory_budget,
            merge_ratio=self._merge_ratio,
        )

    def apply_similar_memories(
        self,
        bundle: SpeakPromptBundle,
        pulled: SimilarMemoryPullResult,
    ) -> None:
        merged_lines, merged_ids = dedupe_memory_line_pairs(
            list(pulled.social_prefetch_lines)
            + list(pulled.warm_spread_lines)
            + list(pulled.inject.lines),
            list(pulled.social_prefetch_unit_ids)
            + list(pulled.warm_spread_unit_ids)
            + list(pulled.inject.unit_ids),
        )
        inject_block = render_similar_memories_block(merged_lines)
        if inject_block:
            bundle.injected.status.similar_memories = inject_block

        all_ids = merged_ids
        if all_ids:
            bundle.meta.setdefault("activated_memory_ids", [])
            bundle.meta["activated_memory_ids"].extend(all_ids)

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
                    "social_prefetch_lines": list(pulled.social_prefetch_lines),
                    "warm_spread_lines": list(pulled.warm_spread_lines),
                    "spill_lines": list(pulled.spilled.lines),
                    "spill_unit_ids": list(pulled.spilled.unit_ids),
                    "spill_turn_index": pulled.spilled.turn_index,
                    "sources": list(pulled.sources),
                    "keyword_wait_ms": pulled.keyword_wait_ms,
                    "merge_ratio": pulled.merge_ratio,
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
            wait_ms=self._portrait_wait_ms,
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
        self.request_emergence_query(
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
        self.request_emergence_query(
            session_id,
            turn_index=turn_index,
            user_text=user_text,
        )
        self.request_keyword_query(
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
