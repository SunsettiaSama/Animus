from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from .chunk import SpeakTurnChunk
from .lifecycle import (
    SPEAK_SESSION_IDLE_SEC,
    SessionBootstrap,
    SessionEndReason,
    SessionEndResult,
    SessionHolder,
    SessionOpenResult,
    SessionOpenTrigger,
    SessionStarter,
    SpeakSessionRegistry,
    TurnRecordResult,
)
from .queue import (
    InterruptContext,
    QueueDecisionResult,
    SessionComposeQueue,
    SessionQueueHub,
    SessionUserQueue,
    SubmitUserInputResult,
    UserInputItem,
)

if TYPE_CHECKING:
    from agent.soul.presence.service import PresenceService
    from agent.soul.speak.session.lifecycle.hold.semantic import SemanticSessionBoundary
    from ..io.inbound.ingest import SpeakIngestResult
else:
    SpeakIngestResult = object  # noqa: N806


class SpeakSessionService:
    """Speak 会话服务：生命周期 + 队列，对外统一入口。"""

    def __init__(
        self,
        *,
        presence: PresenceService | None = None,
        semantic: SemanticSessionBoundary | None = None,
        idle_sec: float = SPEAK_SESSION_IDLE_SEC,
        inner_lifecycle=None,
        touch_dialogue: Callable[[str], None] | None = None,
        registry: SpeakSessionRegistry | None = None,
        reset_context: Callable[[str], None] | None = None,
    ) -> None:
        self._queues = SessionQueueHub()
        self._bootstrap = SessionBootstrap(
            idle_sec=idle_sec,
            inner_lifecycle=inner_lifecycle,
            touch_dialogue=touch_dialogue,
            registry=registry,
            reset_context=reset_context,
        )
        self._holder = SessionHolder(
            self._bootstrap,
            semantic=semantic,
            on_rotate=self._queues.clear_session,
        )
        self._starter = SessionStarter(
            self._bootstrap,
            presence=presence,
            on_rotate=self._queues.clear_session,
        )

    @property
    def registry(self) -> SpeakSessionRegistry:
        return self._bootstrap.registry

    @property
    def compose_queue(self) -> SessionComposeQueue:
        return self._queues.compose_queue

    @property
    def user_queue(self) -> SessionUserQueue:
        return self._queues.user_queue

    @property
    def queues(self) -> SessionQueueHub:
        return self._queues

    @property
    def bootstrap(self) -> SessionBootstrap:
        return self._bootstrap

    @property
    def holder(self) -> SessionHolder:
        return self._holder

    def bind_record_fn(self, record_fn: Callable[[SpeakTurnChunk], SpeakIngestResult]) -> None:
        self._holder.bind_record_fn(record_fn)

    def bind_compose_scheduler(self, schedule_compose: Callable[[str, str], None]) -> None:
        self._queues.bind_compose_scheduler(schedule_compose)

    def bind_queue_decision_scheduler(
        self,
        schedule_decision: Callable[[str, InterruptContext, int], None],
    ) -> None:
        self._queues.bind_queue_decision_scheduler(schedule_decision)

    def open(
        self,
        session_id: str,
        *,
        trigger: SessionOpenTrigger = "user_message",
        proactive_message: str = "",
        proactive_intent_id: str = "",
    ) -> SessionOpenResult:
        return self._starter.open(
            session_id,
            trigger=trigger,
            proactive_message=proactive_message,
            proactive_intent_id=proactive_intent_id,
        )

    def terminate(
        self,
        session_id: str,
        *,
        reason: SessionEndReason,
        note: str = "",
    ) -> SessionEndResult:
        return self._holder.terminate(session_id, reason=reason, note=note)

    def record_turn(
        self,
        chunk: SpeakTurnChunk,
        *,
        on_after: Callable[[str], None] | None = None,
    ) -> TurnRecordResult:
        return self._holder.record_turn(chunk, on_after=on_after)

    def is_pushing(self, session_id: str) -> bool:
        return self._queues.is_pushing(session_id)

    def submit_user_input(
        self,
        session_id: str,
        user_text: str,
        *,
        stream: bool = False,
        mode: str = "inbound",
        record: bool = True,
    ) -> SubmitUserInputResult:
        return self._queues.submit_user_input(
            session_id,
            user_text,
            stream=stream,
            mode=mode,
            record=record,
        )

    def pop_pending_user_input(self, session_id: str) -> UserInputItem | None:
        return self._queues.pop_pending_user_input(session_id)

    def begin_push(self, session_id: str, user_text: str) -> None:
        self._queues.begin_push(session_id, user_text)

    def update_partial_output(self, session_id: str, partial: str) -> None:
        self._queues.update_partial_output(session_id, partial)

    def end_push(self, session_id: str, *, partial_output: str = "") -> InterruptContext | None:
        return self._queues.end_push(session_id, partial_output=partial_output)

    def on_queue_decision_complete(
        self,
        session_id: str,
        token: int,
        result: QueueDecisionResult,
    ) -> None:
        self._queues.on_queue_decision_complete(session_id, token, result)

    def prepare_interrupt_turn(
        self,
        session_id: str,
        item: UserInputItem,
    ) -> InterruptContext | None:
        return self._queues.prepare_interrupt_turn(session_id, item)

    def render_interrupt_block(self, ctx: InterruptContext) -> str:
        return self._queues.render_interrupt_block(ctx)

    def on_compose_ready(self, frame, *, mode: str = "inbound") -> None:
        self._queues.on_compose_ready(frame, mode=mode)

    def pop_compose(self, session_id: str, *, mode: str = "inbound"):
        return self._queues.pop_compose(session_id, mode=mode)

    def clear_compose(self, session_id: str) -> None:
        self._queues.clear_session(session_id)


SpeakSessionManager = SpeakSessionService
