from __future__ import annotations

from collections.abc import Callable

from agent.soul.memory.emergence.line_dedup import dedupe_memory_line_pairs
from agent.soul.speak.orchestrator.guidance.memory.candidates import (
    build_recall_candidates_from_pull,
    format_recall_candidates,
)
from agent.soul.speak.orchestrator.guidance.memory.pick_weights import RecallPickWeightPort
from agent.soul.speak.orchestrator.guidance.memory import (
    format_interactor_preview,
    render_interactor_portrait_inject,
)
from agent.soul.speak.orchestrator.prompt_trace import get_prompt_trace

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
    """Memory 入站：画像/涌现记忆写入 guidance 候选，供引导规划器决策。"""

    def __init__(
        self,
        gateway: InboundMemoryGateway,
        *,
        get_bound_interactor: GetBoundInteractor,
        keyword_wait_ms: int = 200,
        memory_budget: int = 5,
        portrait_wait_ms: int = 100,
        merge_ratio: float | None = None,
        recall_pick_weights: RecallPickWeightPort | None = None,
    ) -> None:
        self._gateway = gateway
        self._get_bound_interactor = get_bound_interactor
        self._keyword_wait_ms = max(0, keyword_wait_ms)
        self._memory_budget = max(1, memory_budget)
        self._portrait_wait_ms = max(0, portrait_wait_ms)
        self._merge_ratio = merge_ratio
        self._recall_pick_weights = recall_pick_weights

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
        *,
        user_text: str = "",
    ) -> SimilarMemoryPullResult:
        return self._gateway.pull_similar_memories(
            session_id,
            turn_index,
            keyword_wait_ms=self._keyword_wait_ms,
            budget=self._memory_budget,
            merge_ratio=self._merge_ratio,
            user_text=user_text,
        )

    def apply_similar_memories(
        self,
        bundle,
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
        recall_candidates = build_recall_candidates_from_pull(
            pulled,
            session_id=bundle.session_id,
            pick_weights=self._recall_pick_weights,
        )
        preview = format_recall_candidates(recall_candidates)
        if preview:
            bundle.guidance.recall_preview = preview
            bundle.meta["guidance_recall_candidates"] = recall_candidates

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
        bundle,
        pulled: InteractorPortraitPullResult,
    ) -> None:
        block = render_interactor_portrait_inject(pulled.portrait_text)
        preview = format_interactor_preview(block or pulled.portrait_text)
        if preview:
            bundle.guidance.interactor_portrait = preview
        if pulled.interactor_id:
            bundle.meta["resolved_interactor_id"] = pulled.interactor_id
        if pulled.turn_index:
            bundle.meta["interactor_portrait_turn_index"] = pulled.turn_index
        snippets = getattr(pulled, "neighborhood_snippets", ()) or ()
        if snippets:
            bundle.meta["interactor_neighborhood_snippets"] = list(snippets)
        if get_prompt_trace().is_enabled(bundle.session_id):
            trace_pull = bundle.meta.setdefault("trace_pull", {})
            if isinstance(trace_pull, dict):
                trace_pull["portrait"] = {
                    "portrait_text": pulled.portrait_text,
                    "interactor_id": pulled.interactor_id,
                    "turn_index": pulled.turn_index,
                    "neighborhood_snippets": list(snippets),
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
        bundle,
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
        ledger=None,
    ) -> tuple[SimilarMemoryPullResult, InteractorPortraitPullResult]:
        if ledger is not None:
            if not ledger.emergence_requested:
                self.request_emergence_query(
                    session_id,
                    turn_index=turn_index,
                    user_text=user_text,
                )
                ledger.emergence_requested = True
            if not ledger.keyword_requested:
                self.request_keyword_query(
                    session_id,
                    turn_index=turn_index,
                    user_text=user_text,
                )
                ledger.keyword_requested = True
            if not ledger.portrait_requested:
                self.request_interactor_portrait(
                    session_id,
                    turn_index=turn_index,
                    user_text=user_text,
                )
                ledger.portrait_requested = True
        return (
            self.pull_similar_memories(session_id, turn_index, user_text=user_text),
            self.pull_interactor_portrait(session_id, turn_index),
        )

    def apply_compose_context(
        self,
        bundle,
        *,
        similar: SimilarMemoryPullResult,
        portrait: InteractorPortraitPullResult,
    ) -> None:
        self.apply_similar_memories(bundle, similar)
        self.apply_interactor_portrait(bundle, portrait)
