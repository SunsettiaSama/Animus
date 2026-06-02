from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .compose import SessionComposeQueue
from .decision import QueueDecisionResult
from .memory import (
    MemoryBufferItem,
    MemoryBufferSource,
    MemoryComposePullResult,
    MemoryQueueConsumeResult,
    MemoryQueueItem,
    SessionMemoryBuffer,
)
from .portrait import PortraitQueueConsumeResult, PortraitQueueItem, SessionPortraitQueue
from .share import SessionShareQueue
from agent.soul.speak.orchestrator.guidance.interrupt import render_interrupt_system_block

from .interrupt import summarize_suspended_compose
from ..pacing import SessionUtterancePacing, UtteranceHoldPreset
from .types import BrewLine, InterruptContext, SessionRuntime, SubmitUserInputResult, SpeakTurnMode
from .user import SessionUserQueue, UserInputItem

try:
    from agent.soul.speak.orchestrator.memory import MemoryWarmBuffer
except ImportError:
    MemoryWarmBuffer = None  # type: ignore[misc, assignment]


class SessionQueueHub:
    """队列与会话推送态：compose / user 队列、插队、异步决策。"""

    def __init__(
        self,
        *,
        memory_turn_gap: int = 3,
        brew_queue_max: int = 3,
        typing_idle_ms: int = 3000,
    ) -> None:
        self._compose_queue = SessionComposeQueue()
        self._user_queue = SessionUserQueue()
        self._memory_turn_gap = memory_turn_gap
        self._brew_queue_max = max(1, brew_queue_max)
        self._typing_idle_ms_default = max(500, typing_idle_ms)
        self._memory_resolve: Callable[[str], SessionMemoryBuffer] | None = None
        self._fallback_memory = SessionMemoryBuffer(max_turn_gap=memory_turn_gap)
        self._portrait_queue = SessionPortraitQueue(max_turn_gap=memory_turn_gap)
        self._share_queue = SessionShareQueue()
        self._runtimes: dict[str, SessionRuntime] = {}
        self._schedule_compose: Callable[[str, str], None] | None = None
        self._schedule_queue_decision: Callable[[str, InterruptContext, int], None] | None = None
        self._on_typing_start: Callable[[str], None] | None = None
        self._on_typing_idle: Callable[[str], None] | None = None

    def bind_compose_scheduler(self, schedule_compose: Callable[[str, str], None]) -> None:
        self._schedule_compose = schedule_compose

    def bind_queue_decision_scheduler(
        self,
        schedule_decision: Callable[[str, InterruptContext, int], None],
    ) -> None:
        self._schedule_queue_decision = schedule_decision

    def bind_memory_warm_buffer(
        self,
        resolver: Callable[[str], SessionMemoryBuffer],
    ) -> None:
        self._memory_resolve = resolver

    def _memory_for(self, session_id: str) -> SessionMemoryBuffer:
        if self._memory_resolve is not None:
            return self._memory_resolve(session_id)
        return self._fallback_memory

    def _runtime(self, session_id: str) -> SessionRuntime:
        if session_id not in self._runtimes:
            self._runtimes[session_id] = SessionRuntime(
                session_id=session_id,
                typing_idle_ms=self._typing_idle_ms_default,
            )
        return self._runtimes[session_id]

    def utterance_pacing(self, session_id: str) -> SessionUtterancePacing:
        return self._runtime(session_id).pacing

    def set_utterance_hold(
        self,
        session_id: str,
        *,
        enabled: bool,
        hold_ms: UtteranceHoldPreset = 3000,
    ) -> SessionUtterancePacing:
        """Deprecated：映射为 typing_idle_ms，不再阻塞 compose。"""
        runtime = self._runtime(session_id)
        runtime.pacing.enabled = False
        runtime.pacing.hold_ms = 5000 if hold_ms == 5000 else 3000
        runtime.typing_idle_ms = runtime.pacing.hold_ms
        _ = enabled
        return runtime.pacing

    def bind_typing_start(self, handler: Callable[[str], None]) -> None:
        self._on_typing_start = handler

    def bind_typing_idle(self, handler: Callable[[str], None]) -> None:
        self._on_typing_idle = handler

    def push_phase(self, session_id: str) -> str:
        runtime = self._runtime(session_id)
        with runtime.lock:
            return runtime.phase

    def wait_typing_idle(self, session_id: str, *, timeout: float = 120.0) -> bool:
        runtime = self._runtime(session_id)
        with runtime.lock:
            if runtime.typing_idle and not runtime.typing_active:
                return True
        return runtime.typing_idle_event.wait(timeout=timeout)

    def wait_typing_idle_handoff(self, session_id: str, *, timeout: float = 120.0) -> bool:
        """等待 typing_idle 后导演决策 + 酝酿出队完成。"""
        runtime = self._runtime(session_id)
        return runtime.typing_idle_handoff.wait(timeout=timeout)

    def is_typing_without_idle(self, session_id: str) -> bool:
        runtime = self._runtime(session_id)
        with runtime.lock:
            return runtime.typing_active and not runtime.typing_idle

    def merge_pending_user_text(self, session_id: str, text: str) -> str:
        runtime = self._runtime(session_id)
        with runtime.lock:
            return runtime.merge_pending_user_text(text)

    def set_pending_turn(
        self,
        session_id: str,
        *,
        stream: bool,
        record: bool,
        mode: SpeakTurnMode,
    ) -> None:
        runtime = self._runtime(session_id)
        with runtime.lock:
            runtime.pending_stream = stream
            runtime.pending_record = record
            runtime.pending_mode = mode

    def pop_pending_turn(self, session_id: str) -> tuple[str, bool, bool, SpeakTurnMode] | None:
        runtime = self._runtime(session_id)
        with runtime.lock:
            text = runtime.pending_user_text.strip()
            if not text:
                return None
            payload = (
                text,
                runtime.pending_stream,
                runtime.pending_record,
                runtime.pending_mode,
            )
            runtime.pending_user_text = ""
            runtime.pending_stream = False
            return payload

    def on_typing_pulse(
        self,
        session_id: str,
        *,
        typing: bool,
        draft: str = "",
    ) -> dict[str, object]:
        runtime = self._runtime(session_id)
        notes: list[str] = []
        fire_start = False
        with runtime.lock:
            was_active = runtime.typing_active
            runtime.draft_user_text = draft.strip() if draft else runtime.draft_user_text
            if typing:
                runtime.typing_active = True
                runtime.typing_idle = False
                runtime.typing_idle_event.clear()
                runtime.typing_idle_handoff.clear()
                runtime.last_typing_at = time.monotonic()
                if not was_active:
                    fire_start = True
                    notes.append("typing: start edge")
            else:
                runtime.typing_active = False
                notes.append("typing: pulse false (debounce idle)")
            self._reschedule_idle_timer_locked(runtime)

        if fire_start and self._on_typing_start is not None:
            self._on_typing_start(session_id)
        snap = self._runtime(session_id)
        with snap.lock:
            return {**snap.snapshot_typing(), "notes": notes}

    def enqueue_brew(self, session_id: str, text: str, *, reason: str = "") -> bool:
        line = text.strip()
        if not line:
            return False
        runtime = self._runtime(session_id)
        with runtime.lock:
            if len(runtime.brew_queue) >= self._brew_queue_max:
                runtime.brew_queue.pop(0)
            runtime.brew_queue.append(BrewLine(text=line[:40], reason=reason))
            return True

    def flush_brew(self, session_id: str) -> list[str]:
        runtime = self._runtime(session_id)
        with runtime.lock:
            lines = [item.text for item in runtime.brew_queue if item.text.strip()]
            runtime.brew_queue.clear()
            return lines

    def brew_queue_snapshot(self, session_id: str) -> dict[str, object]:
        runtime = self._runtime(session_id)
        with runtime.lock:
            return {
                "depth": len(runtime.brew_queue),
                "lines": [item.text for item in runtime.brew_queue],
            }

    def _reschedule_idle_timer_locked(self, runtime: SessionRuntime) -> None:
        if runtime.idle_timer is not None:
            runtime.idle_timer.cancel()
            runtime.idle_timer = None
        if not runtime.typing_active and runtime.last_typing_at <= 0:
            runtime.typing_idle = True
            return
        delay_sec = max(0.5, runtime.typing_idle_ms / 1000.0)
        runtime.idle_timer = threading.Timer(
            delay_sec,
            self._fire_typing_idle,
            args=(runtime.session_id,),
        )
        runtime.idle_timer.daemon = True
        runtime.idle_timer.start()

    def _fire_typing_idle(self, session_id: str) -> None:
        runtime = self._runtimes.get(session_id.strip())
        if runtime is None:
            return
        with runtime.lock:
            elapsed_ms = int((time.monotonic() - runtime.last_typing_at) * 1000)
            if runtime.typing_active:
                return
            if runtime.last_typing_at > 0 and elapsed_ms < runtime.typing_idle_ms:
                self._reschedule_idle_timer_locked(runtime)
                return
            runtime.typing_idle = True
            runtime.draft_user_text = ""
            runtime.typing_idle_handoff.clear()
            runtime.typing_idle_event.set()
        if self._on_typing_idle is not None:
            self._on_typing_idle(session_id)
        elif runtime.on_typing_idle is not None:
            runtime.on_typing_idle(session_id)

    @property
    def compose_queue(self) -> SessionComposeQueue:
        return self._compose_queue

    @property
    def user_queue(self) -> SessionUserQueue:
        return self._user_queue

    @property
    def memory_turn_gap(self) -> int:
        return self._memory_turn_gap

    @property
    def memory_queue(self) -> SessionMemoryBuffer:
        return self._fallback_memory

    @property
    def share_queue(self) -> SessionShareQueue:
        return self._share_queue

    def inject_deferred_share_intents(self, session_id: str, intents) -> int:
        return self._share_queue.enqueue_batch(session_id, intents)

    def deferred_share_intents(self, session_id: str):
        return self._share_queue.as_intent_queue(session_id)

    def pop_deferred_share_intent(self, session_id: str):
        return self._share_queue.pop_most_wanted(session_id)

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

    def is_pushing(self, session_id: str) -> bool:
        runtime = self._runtime(session_id)
        with runtime.lock:
            return runtime.phase == "pushing"

    def submit_user_input(
        self,
        session_id: str,
        user_text: str,
        *,
        stream: bool = False,
        mode: str = "inbound",
        record: bool = True,
    ) -> SubmitUserInputResult:
        typed_mode: SpeakTurnMode = "inbound" if mode == "inbound" else "proactive"
        normalized = user_text.strip()
        if not normalized:
            return SubmitUserInputResult(notes=["session: empty user input"])

        runtime = self._runtime(session_id)
        interrupt_ctx: InterruptContext | None = None
        decision_token = 0
        with runtime.lock:
            if runtime.phase == "pushing":
                runtime.interrupt = InterruptContext(
                    new_user_text=normalized,
                    previous_user_text=runtime.active_user_text,
                    partial_agent_output=runtime.partial_agent_output,
                )
                self._suspend_compose_locked(session_id, runtime)
                runtime.interrupt.suspended_compose_count = len(runtime.suspended_compose)
                runtime.interrupt.suspended_compose_summary = summarize_suspended_compose(
                    runtime.suspended_compose,
                )
                runtime.queue_decision_token += 1
                decision_token = runtime.queue_decision_token
                runtime.queue_decision = None
                runtime.queue_decision_pending = True
                runtime.queue_decision_event.clear()
                interrupt_ctx = runtime.interrupt
                self._user_queue.push_front(
                    UserInputItem(
                        session_id=session_id,
                        user_text=normalized,
                        mode=typed_mode,
                        stream=stream,
                        record=record,
                        interrupted=True,
                    ),
                )

            elif self._user_queue.has_pending(session_id):
                self._user_queue.push_front(
                    UserInputItem(
                        session_id=session_id,
                        user_text=normalized,
                        mode=typed_mode,
                        stream=stream,
                        record=record,
                    ),
                )
                return SubmitUserInputResult(
                    queued=True,
                    notes=["session: user input queued"],
                )
            else:
                return SubmitUserInputResult(queued=False)

        if interrupt_ctx is not None:
            if self._schedule_queue_decision is not None:
                self._schedule_queue_decision(session_id, interrupt_ctx, decision_token)
            if self._schedule_compose is not None:
                self._schedule_compose(session_id, typed_mode)
            return SubmitUserInputResult(
                queued=True,
                interrupt=True,
                notes=["session: user interrupt queued"],
            )

        return SubmitUserInputResult(queued=False)

    def pop_pending_user_input(self, session_id: str) -> UserInputItem | None:
        return self._user_queue.pop(session_id)

    def begin_push(self, session_id: str, user_text: str) -> None:
        runtime = self._runtime(session_id)
        with runtime.lock:
            runtime.phase = "pushing"
            runtime.active_user_text = user_text.strip()
            runtime.partial_agent_output = ""

    def update_partial_output(self, session_id: str, partial: str) -> None:
        runtime = self._runtime(session_id)
        with runtime.lock:
            runtime.partial_agent_output = partial.strip()

    def end_push(self, session_id: str, *, partial_output: str = "") -> InterruptContext | None:
        runtime = self._runtime(session_id)
        with runtime.lock:
            runtime.phase = "idle"
            if partial_output.strip():
                runtime.partial_agent_output = partial_output.strip()
            interrupt = runtime.interrupt
            runtime.interrupt = None
            runtime.active_user_text = ""
            return interrupt

    def on_queue_decision_complete(
        self,
        session_id: str,
        token: int,
        result: QueueDecisionResult,
    ) -> None:
        runtime = self._runtime(session_id)
        with runtime.lock:
            if token != runtime.queue_decision_token:
                return
            runtime.queue_decision = result
            runtime.queue_decision_pending = False
            runtime.queue_decision_event.set()

    def await_queue_decision(
        self,
        session_id: str,
        *,
        timeout: float = 30.0,
    ) -> QueueDecisionResult | None:
        runtime = self._runtime(session_id)
        with runtime.lock:
            if not runtime.queue_decision_pending:
                decision = runtime.queue_decision
                if isinstance(decision, QueueDecisionResult):
                    return decision
                return None

        if not runtime.queue_decision_event.wait(timeout=timeout):
            with runtime.lock:
                runtime.queue_decision_pending = False
            return QueueDecisionResult(maintain=False, thought="decision timeout")

        with runtime.lock:
            decision = runtime.queue_decision
            if isinstance(decision, QueueDecisionResult):
                return decision
            return None

    def prepare_interrupt_turn(
        self,
        session_id: str,
        item: UserInputItem,
    ) -> InterruptContext | None:
        if not item.interrupted:
            return None
        ctx = self.interrupt_context_for(session_id, item)
        if ctx is None:
            return None
        decision = self.await_queue_decision(session_id)
        if decision is None:
            return ctx
        if decision.maintain:
            self.resume_suspended_compose(session_id, reorder=decision.reorder)
        else:
            self.drop_suspended_compose(session_id)
        ctx.queue_decision_maintain = decision.maintain
        ctx.queue_decision_thought = decision.thought
        ctx.queue_decision_reorder = decision.reorder
        return ctx

    def interrupt_context_for(self, session_id: str, item: UserInputItem) -> InterruptContext | None:
        if not item.interrupted:
            return None
        runtime = self._runtime(session_id)
        with runtime.lock:
            if runtime.interrupt is not None:
                return runtime.interrupt
            return InterruptContext(
                new_user_text=item.user_text,
                previous_user_text=runtime.partial_agent_output,
                suspended_compose_count=len(runtime.suspended_compose),
                suspended_compose_summary=summarize_suspended_compose(runtime.suspended_compose),
            )

    def render_interrupt_block(self, ctx: InterruptContext) -> str:
        return render_interrupt_system_block(ctx)

    def resume_suspended_compose(
        self,
        session_id: str,
        *,
        reorder: tuple[int, ...] | None = None,
    ) -> int:
        runtime = self._runtime(session_id)
        with runtime.lock:
            items = list(runtime.suspended_compose)
            if reorder is not None and len(reorder) > 1:
                ordered: list = []
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
                self._compose_queue.enqueue(item.frame, mode=item.mode)
                restored += 1
            runtime.suspended_compose.clear()
            return restored

    def drop_suspended_compose(self, session_id: str) -> int:
        runtime = self._runtime(session_id)
        with runtime.lock:
            count = len(runtime.suspended_compose)
            runtime.suspended_compose.clear()
            return count

    def _suspend_compose_locked(self, session_id: str, runtime: SessionRuntime) -> None:
        for mode in ("inbound", "proactive"):
            typed_mode: SpeakTurnMode = mode  # type: ignore[assignment]
            while self._compose_queue.has_pending(session_id, mode=typed_mode):
                item = self._compose_queue.pop(session_id, mode=typed_mode)
                if item is not None:
                    runtime.suspended_compose.append(item)

    def on_compose_ready(self, frame, *, mode: str = "inbound") -> None:
        typed_mode: SpeakTurnMode = "inbound" if mode == "inbound" else "proactive"
        self._compose_queue.enqueue(frame, mode=typed_mode)

    def pop_compose(self, session_id: str, *, mode: str = "inbound"):
        typed_mode: SpeakTurnMode = "inbound" if mode == "inbound" else "proactive"
        return self._compose_queue.pop(session_id, mode=typed_mode)

    def debug_snapshot(self, session_id: str) -> dict[str, object]:
        runtime = self._runtimes.get(session_id)
        phase = "idle"
        partial = ""
        suspended = 0
        if runtime is not None:
            with runtime.lock:
                phase = runtime.phase
                partial = runtime.partial_agent_output
                suspended = len(runtime.suspended_compose)
        return {
            "session_id": session_id,
            "push_phase": phase,
            "partial_agent_output_chars": len(partial),
            "partial_agent_output_preview": partial[:300],
            "suspended_compose_count": suspended,
            "memory_queue": self._memory_for(session_id).peek_session(session_id),
            "portrait_queue": self._portrait_queue.peek_session(session_id),
            "share_queue": self._share_queue.peek_session(session_id),
            "compose_pending_inbound": self._compose_queue.has_pending(session_id, mode="inbound"),
            "compose_pending_proactive": self._compose_queue.has_pending(session_id, mode="proactive"),
            "user_queue_pending": self._user_queue.has_pending(session_id),
        }

    def clear_session(self, session_id: str) -> None:
        self._compose_queue.clear_session(session_id)
        self._memory_for(session_id).clear_session(session_id)
        if self._memory_resolve is not None:
            self._fallback_memory.clear_session(session_id)
        self._portrait_queue.clear_session(session_id)
        self._share_queue.clear_session(session_id)
        runtime = self._runtimes.pop(session_id, None)
        if runtime is not None:
            with runtime.lock:
                if runtime.idle_timer is not None:
                    runtime.idle_timer.cancel()
                    runtime.idle_timer = None
                runtime.suspended_compose.clear()
                runtime.interrupt = None
                runtime.queue_decision = None
                runtime.queue_decision_pending = False
                runtime.queue_decision_token += 1
                runtime.queue_decision_event.set()
                runtime.brew_queue.clear()
                runtime.pending_user_text = ""
        self._user_queue.clear_session(session_id)
