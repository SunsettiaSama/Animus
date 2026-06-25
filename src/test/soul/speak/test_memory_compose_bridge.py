"""Speak ???compose ?? / ???????""
from __future__ import annotations

import threading
import time

from agent.soul.speak.pipelines.request_driven.orchestrator import SpeakPromptBundle
from agent.soul.speak.io.inbound.memory.compose_bridge import InboundMemoryComposeBridge
from agent.soul.speak.io.inbound.memory.gateway import InboundMemoryGateway
from agent.soul.speak.io.inbound.memory.request import (
    SimilarMemoryBlock,
    SimilarMemoryPullResult,
)
from agent.soul.speak.pipelines.request_driven.orchestrator.prompt_trace import get_prompt_trace
from agent.soul.speak.session.queue.memory import MemoryBufferItem, SessionMemoryBuffer
from agent.soul.speak.session.service import SpeakSessionService


def _build_bridge(
    buffer: SessionMemoryBuffer,
    *,
    keyword_wait_ms: int = 200,
    merge_ratio: float | None = None,
) -> InboundMemoryComposeBridge:
    gateway = InboundMemoryGateway()
    manager = SpeakSessionService()
    manager._queues._memory_queue = buffer

    def pull_similar(
        session_id: str,
        turn_index: int,
        wait_ms: int,
        budget: int,
        ratio,
    ) -> SimilarMemoryPullResult:
        consumed = manager.pull_memory_for_compose(
            session_id,
            turn_index,
            keyword_wait_ms=wait_ms,
            budget=budget,
            merge_ratio=ratio,
        )
        inject_turn = (
            consumed.inject_turn_indices[0]
            if consumed.inject_turn_indices
            else turn_index
        )
        return SimilarMemoryPullResult(
            inject=SimilarMemoryBlock(
                turn_index=inject_turn,
                lines=list(consumed.inject_lines),
                unit_ids=list(consumed.inject_unit_ids),
            ),
            social_prefetch_lines=list(consumed.social_prefetch_lines),
            social_prefetch_unit_ids=list(consumed.social_prefetch_unit_ids),
            warm_spread_lines=list(consumed.warm_spread_lines),
            warm_spread_unit_ids=list(consumed.warm_spread_unit_ids),
            merge_ratio=consumed.merge_ratio,
            keyword_wait_ms=consumed.keyword_wait_ms,
            sources=list(consumed.sources),
        )

    bridge = InboundMemoryComposeBridge(
        gateway,
        get_bound_interactor=lambda _sid: "interactor-1",
        keyword_wait_ms=keyword_wait_ms,
        memory_budget=5,
        merge_ratio=merge_ratio,
    )
    bridge.attach_ports(
        point_query_fn=lambda _req: None,
        keyword_query_fn=lambda _req: None,
        pull_similar_fn=pull_similar,
    )
    return bridge


def test_pull_compose_context_waits_for_keyword():
    buffer = SessionMemoryBuffer()
    bridge = _build_bridge(buffer, keyword_wait_ms=200)

    def delayed_enqueue() -> None:
        time.sleep(0.05)
        buffer.enqueue_turn(
            "s-wait",
            MemoryBufferItem(
                turn_index=2,
                lines=("?????,),
                unit_ids=("u-kw",),
                source="keyword",
            ),
        )

    threading.Thread(target=delayed_enqueue, daemon=True).start()
    similar, _ = bridge.pull_compose_context(
        "s-wait",
        user_text="?????,
        turn_index=2,
    )

    assert "u-kw" in similar.inject.unit_ids
    assert "????? in similar.inject.lines


def test_pull_compose_context_includes_social_prefetch_slot():
    buffer = SessionMemoryBuffer()
    buffer.set_social_prefetch(
        "s-social",
        MemoryBufferItem(
            turn_index=0,
            lines=("????",),
            unit_ids=("u-social",),
            source="social_prefetch",
        ),
    )
    buffer.enqueue_turn(
        "s-social",
        MemoryBufferItem(
            turn_index=2,
            lines=("???,),
            unit_ids=("u-kw",),
            source="keyword",
        ),
    )
    bridge = _build_bridge(buffer, keyword_wait_ms=0, merge_ratio=1.0)

    bundle = SpeakPromptBundle(session_id="s-social")
    similar, _ = bridge.pull_compose_context(
        "s-social",
        user_text="??",
        turn_index=2,
    )
    bridge.apply_similar_memories(bundle, similar)

    assert "????" in bundle.guidance.recall_preview
    assert "u-social" in bundle.meta.get("activated_memory_ids", [])


def test_empty_pull_writes_no_similar_block():
    buffer = SessionMemoryBuffer()
    bridge = _build_bridge(buffer, keyword_wait_ms=0)
    bundle = SpeakPromptBundle(session_id="s-empty")
    get_prompt_trace().set_session("s-empty", True)
    similar, _ = bridge.pull_compose_context(
        "s-empty",
        user_text="?????,
        turn_index=2,
    )
    bridge.apply_similar_memories(bundle, similar)

    assert similar.inject.unit_ids == []
    assert bundle.guidance.recall_preview == ""
