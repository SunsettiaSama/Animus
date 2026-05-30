from __future__ import annotations

from collections.abc import Callable

from .compose import SessionComposeQueue
from .decision import QueueDecisionResult
from .memory import MemoryQueueConsumeResult, MemoryQueueItem, SessionMemoryQueue
from .portrait import PortraitQueueConsumeResult, PortraitQueueItem, SessionPortraitQueue
from .share import SessionShareQueue
from .interrupt import render_interrupt_system_block, summarize_suspended_compose
from .types import InterruptContext, SessionRuntime, SubmitUserInputResult, SpeakTurnMode
from .user import SessionUserQueue, UserInputItem


class SessionQueueHub:
    """队列与会话推送态：compose / user 队列、插队、异步决策。"""

    def __init__(self, *, memory_turn_gap: int = 3) -> None:
        self._compose_queue = SessionComposeQueue()
        self._user_queue = SessionUserQueue()
        self._memory_queue = SessionMemoryQueue(max_turn_gap=memory_turn_gap)
        self._portrait_queue = SessionPortraitQueue(max_turn_gap=memory_turn_gap)
        self._share_queue = SessionShareQueue()
        self._runtimes: dict[str, SessionRuntime] = {}
        self._schedule_compose: Callable[[str, str], None] | None = None
        self._schedule_queue_decision: Callable[[str, InterruptContext, int], None] | None = None

    def bind_compose_scheduler(self, schedule_compose: Callable[[str, str], None]) -> None:
        self._schedule_compose = schedule_compose

    def bind_queue_decision_scheduler(
        self,
        schedule_decision: Callable[[str, InterruptContext, int], None],
    ) -> None:
        self._schedule_queue_decision = schedule_decision

    def _runtime(self, session_id: str) -> SessionRuntime:
        if session_id not in self._runtimes:
            self._runtimes[session_id] = SessionRuntime(session_id=session_id)
        return self._runtimes[session_id]

    @property
    def compose_queue(self) -> SessionComposeQueue:
        return self._compose_queue

    @property
    def user_queue(self) -> SessionUserQueue:
        return self._user_queue

    @property
    def memory_queue(self) -> SessionMemoryQueue:
        return self._memory_queue

    @property
    def share_queue(self) -> SessionShareQueue:
        return self._share_queue

    def inject_deferred_share_intents(self, session_id: str, intents) -> int:
        return self._share_queue.enqueue_batch(session_id, intents)

    def deferred_share_intents(self, session_id: str):
        return self._share_queue.as_intent_queue(session_id)

    def pop_deferred_share_intent(self, session_id: str):
        return self._share_queue.pop_most_wanted(session_id)

    def enqueue_memory(self, session_id: str, item: MemoryQueueItem) -> None:
        self._memory_queue.enqueue(session_id, item)

    def consume_memory_for_compose(
        self,
        session_id: str,
        current_turn_index: int,
    ) -> MemoryQueueConsumeResult:
        return self._memory_queue.consume_for_compose(session_id, current_turn_index)

    def pull_memory_for_compose(
        self,
        session_id: str,
        current_turn_index: int,
        *,
        wait_ms: int = 0,
    ) -> MemoryQueueConsumeResult:
        return self._memory_queue.pull_for_compose(
            session_id,
            current_turn_index,
            wait_ms=wait_ms,
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
            "memory_queue": self._memory_queue.peek_session(session_id),
            "portrait_queue": self._portrait_queue.peek_session(session_id),
            "share_queue": self._share_queue.peek_session(session_id),
            "compose_pending_inbound": self._compose_queue.has_pending(session_id, mode="inbound"),
            "compose_pending_proactive": self._compose_queue.has_pending(session_id, mode="proactive"),
            "user_queue_pending": self._user_queue.has_pending(session_id),
        }

    def clear_session(self, session_id: str) -> None:
        self._compose_queue.clear_session(session_id)
        self._memory_queue.clear_session(session_id)
        self._portrait_queue.clear_session(session_id)
        self._share_queue.clear_session(session_id)
        runtime = self._runtimes.get(session_id)
        if runtime is not None:
            with runtime.lock:
                runtime.suspended_compose.clear()
                runtime.interrupt = None
                runtime.queue_decision = None
                runtime.queue_decision_pending = False
                runtime.queue_decision_token += 1
                runtime.queue_decision_event.set()
        self._user_queue.clear_session(session_id)
