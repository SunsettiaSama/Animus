from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.guidance.session_bridge import (
    render_interrupt_system_block,
)
from agent.soul.speak.session.queue.types import InterruptContext, SpeakTurnMode

from .compose import ComposeFrameQueue, ComposeQueueItem
from .decision import QueueDecisionResult
from .interrupt import summarize_suspended_compose
from .memory import (
    ComposeMemoryBuffer,
    MemoryBufferItem,
    MemoryComposePullResult,
)
from .portrait import ComposePortraitQueue, PortraitQueueConsumeResult, PortraitQueueItem

try:
    from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.memory.warm_buffer import MemoryWarmBuffer
except ImportError:
    MemoryWarmBuffer = None  # type: ignore[misc, assignment]


@dataclass
class _ComposeDecisionState:
    pending: bool = False
    token: int = 0
    result: QueueDecisionResult | None = None
    event: threading.Event = field(default_factory=threading.Event)


class ComposeQueueHub:
    """提示词调度队列：compose 帧 / 记忆画像注入 / 插队决策。"""

    def __init__(self, *, memory_turn_gap: int = 3) -> None:
        self._frame_queue = ComposeFrameQueue()
        self._memory_turn_gap = memory_turn_gap
        self._memory_resolve: Callable[[str], ComposeMemoryBuffer] | None = None
        self._fallback_memory = ComposeMemoryBuffer(max_turn_gap=memory_turn_gap)
        self._portrait_queue = ComposePortraitQueue(max_turn_gap=memory_turn_gap)
        self._suspended: dict[str, list[ComposeQueueItem]] = {}
        self._decisions: dict[str, _ComposeDecisionState] = {}
        self._schedule_compose: Callable[[str, str], None] | None = None
        self._schedule_queue_decision: Callable[[str, InterruptContext, int], None] | None = None

    @property
    def frame_queue(self) -> ComposeFrameQueue:
        return self._frame_queue

    @property
    def memory_turn_gap(self) -> int:
        return self._memory_turn_gap

    @property
    def memory_buffer(self) -> ComposeMemoryBuffer:
        return self._fallback_memory

    def bind_compose_scheduler(self, schedule_compose: Callable[[str, str], None]) -> None:
        self._schedule_compose = schedule_compose

    def bind_queue_decision_scheduler(
        self,
        schedule_decision: Callable[[str, InterruptContext, int], None],
    ) -> None:
        self._schedule_queue_decision = schedule_decision

    def bind_memory_buffer(self, resolver: Callable[[str], ComposeMemoryBuffer]) -> None:
        self._memory_resolve = resolver

    def _memory_for(self, session_id: str) -> ComposeMemoryBuffer:
        if self._memory_resolve is not None:
            return self._memory_resolve(session_id)
        return self._fallback_memory

    def _decision_state(self, session_id: str) -> _ComposeDecisionState:
        sid = session_id.strip()
        if sid not in self._decisions:
            self._decisions[sid] = _ComposeDecisionState()
        return self._decisions[sid]

    def on_frame_ready(self, frame, *, mode: str = "inbound") -> None:
        typed_mode: SpeakTurnMode = "inbound" if mode == "inbound" else "proactive"
        self._frame_queue.enqueue(frame, mode=typed_mode)

    def pop_frame(self, session_id: str, *, mode: str = "inbound") -> ComposeQueueItem | None:
        typed_mode: SpeakTurnMode = "inbound" if mode == "inbound" else "proactive"
        return self._frame_queue.pop(session_id, mode=typed_mode)

    def has_pending(self, session_id: str, *, mode: str = "inbound") -> bool:
        typed_mode: SpeakTurnMode = "inbound" if mode == "inbound" else "proactive"
        return self._frame_queue.has_pending(session_id, mode=typed_mode)

    def has_any_pending(self, session_id: str) -> bool:
        return (
            self.has_pending(session_id, mode="inbound")
            or self.has_pending(session_id, mode="proactive")
        )

    def schedule_compose(self, session_id: str, mode: SpeakTurnMode) -> None:
        if self._schedule_compose is not None:
            self._schedule_compose(session_id, mode)

    def suspend_session(self, session_id: str) -> tuple[int, str]:
        sid = session_id.strip()
        suspended: list[ComposeQueueItem] = []
        for mode in ("inbound", "proactive"):
            typed_mode: SpeakTurnMode = mode  # type: ignore[assignment]
            while self._frame_queue.has_pending(sid, mode=typed_mode):
                item = self._frame_queue.pop(sid, mode=typed_mode)
                if item is not None:
                    suspended.append(item)
        self._suspended[sid] = suspended
        return len(suspended), summarize_suspended_compose(suspended)

    def resume_suspended(
        self,
        session_id: str,
        *,
        reorder: tuple[int, ...] | None = None,
    ) -> int:
        sid = session_id.strip()
        items = list(self._suspended.get(sid, []))
        if reorder is not None and len(reorder) > 1:
            ordered: list[ComposeQueueItem] = []
            for index in reorder:
                if 1 <= index <= len(items):
                    ordered.append(items[index - 1])
            seen = set(reorder)
            for index, item in enumerate(items, start=1):
                if index not in seen:
                    ordered.append(item)
            items = ordered
        restored = 0
        for item in items:
            self._frame_queue.enqueue(item.frame, mode=item.mode)
            restored += 1
        self._suspended.pop(sid, None)
        return restored

    def drop_suspended(self, session_id: str) -> int:
        sid = session_id.strip()
        count = len(self._suspended.get(sid, []))
        self._suspended.pop(sid, None)
        return count

    def begin_queue_decision(self, session_id: str) -> int:
        state = self._decision_state(session_id)
        state.token += 1
        state.pending = True
        state.result = None
        state.event.clear()
        return state.token

    def on_queue_decision_complete(
        self,
        session_id: str,
        token: int,
        result: QueueDecisionResult,
    ) -> None:
        state = self._decision_state(session_id)
        if token != state.token:
            return
        state.result = result
        state.pending = False
        state.event.set()

    def await_queue_decision(
        self,
        session_id: str,
        *,
        timeout: float = 30.0,
    ) -> QueueDecisionResult | None:
        state = self._decision_state(session_id)
        if not state.pending:
            return state.result
        if not state.event.wait(timeout=timeout):
            state.pending = False
            return QueueDecisionResult(maintain=False, thought="decision timeout")
        return state.result

    def request_queue_decision(
        self,
        session_id: str,
        ctx: InterruptContext,
        token: int,
    ) -> None:
        if self._schedule_queue_decision is not None:
            self._schedule_queue_decision(session_id, ctx, token)

    def prepare_interrupt_turn(
        self,
        session_id: str,
        ctx: InterruptContext,
    ) -> InterruptContext:
        decision = self.await_queue_decision(session_id)
        if decision is None:
            return ctx
        if decision.maintain:
            self.resume_suspended(session_id, reorder=decision.reorder)
        else:
            self.drop_suspended(session_id)
        ctx.queue_decision_maintain = decision.maintain
        ctx.queue_decision_thought = decision.thought
        ctx.queue_decision_reorder = decision.reorder
        return ctx

    def render_interrupt_block(self, ctx: InterruptContext) -> str:
        return render_interrupt_system_block(ctx)

    def enqueue_memory(self, session_id: str, item: MemoryBufferItem) -> None:
        self._memory_for(session_id).enqueue_turn(session_id, item)

    def set_social_prefetch(self, session_id: str, item: MemoryBufferItem) -> None:
        self._memory_for(session_id).set_social_prefetch(session_id, item)

    def set_warm_spread(self, session_id: str, item: MemoryBufferItem) -> None:
        self._memory_for(session_id).set_warm_spread(session_id, item)

    def pull_memory_for_compose(
        self,
        session_id: str,
        current_turn_index: int,
        *,
        keyword_wait_ms: int = 200,
        budget: int = 5,
        merge_ratio: float | None = None,
        user_text: str = "",
    ) -> MemoryComposePullResult:
        memory = self._memory_for(session_id)
        if MemoryWarmBuffer is not None and isinstance(memory, MemoryWarmBuffer):
            return memory.pull_for_compose(
                session_id,
                current_turn_index,
                keyword_wait_ms=keyword_wait_ms,
                budget=budget,
                merge_ratio=merge_ratio,
                user_text=user_text,
            )
        return memory.pull_for_compose(
            session_id,
            current_turn_index,
            keyword_wait_ms=keyword_wait_ms,
            budget=budget,
            merge_ratio=merge_ratio,
        )

    def enqueue_portrait(self, session_id: str, item: PortraitQueueItem) -> None:
        self._portrait_queue.enqueue(session_id, item)

    def consume_portrait_for_compose(
        self,
        session_id: str,
        current_turn_index: int,
    ) -> PortraitQueueConsumeResult:
        return self._portrait_queue.consume_for_compose(session_id, current_turn_index)

    def pull_portrait_for_compose(
        self,
        session_id: str,
        current_turn_index: int,
        *,
        wait_ms: int = 0,
    ) -> PortraitQueueConsumeResult:
        return self._portrait_queue.pull_for_compose(
            session_id,
            current_turn_index,
            wait_ms=wait_ms,
        )

    def debug_snapshot(self, session_id: str) -> dict[str, Any]:
        return {
            "compose_pending_inbound": self.has_pending(session_id, mode="inbound"),
            "compose_pending_proactive": self.has_pending(session_id, mode="proactive"),
            "suspended_compose_count": len(self._suspended.get(session_id.strip(), [])),
            "memory_queue": self._memory_for(session_id).peek_session(session_id),
            "portrait_queue": self._portrait_queue.peek_session(session_id),
        }

    def clear_session(self, session_id: str) -> None:
        sid = session_id.strip()
        self._frame_queue.clear_session(sid)
        self._memory_for(sid).clear_session(sid)
        if self._memory_resolve is not None:
            self._fallback_memory.clear_session(sid)
        self._portrait_queue.clear_session(sid)
        self._suspended.pop(sid, None)
        state = self._decisions.pop(sid, None)
        if state is not None:
            state.pending = False
            state.token += 1
            state.event.set()
