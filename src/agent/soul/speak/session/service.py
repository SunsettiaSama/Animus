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
    SessionQueueHub,
    SessionUserQueue,
    SubmitUserInputResult,
    UserInputItem,
)
from .manage import SessionSocialManager

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
        brew_queue_max: int = 3,
        typing_idle_ms: int = 3000,
        compose_pending: Callable[[str], bool] | None = None,
    ) -> None:
        self._queues = SessionQueueHub(
            brew_queue_max=brew_queue_max,
            typing_idle_ms=typing_idle_ms,
        )
        self._compose_pending = compose_pending
        self._bootstrap = SessionBootstrap(
            idle_sec=idle_sec,
            inner_lifecycle=inner_lifecycle,
            touch_dialogue=touch_dialogue,
            registry=registry,
            reset_context=reset_context,
        )
        self._social = SessionSocialManager(registry=self._bootstrap.registry)
        self._wrap_queue_clear()
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

    def _wrap_queue_clear(self) -> None:
        original = self._queues.clear_session

        def _clear(session_id: str) -> None:
            self._social.clear_session(session_id)
            original(session_id)

        self._queues.clear_session = _clear  # type: ignore[method-assign]

    @property
    def social(self) -> SessionSocialManager:
        return self._social

    @property
    def registry(self) -> SpeakSessionRegistry:
        return self._bootstrap.registry

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

    def utterance_pacing(self, session_id: str):
        return self._queues.utterance_pacing(session_id)

    def set_utterance_hold(
        self,
        session_id: str,
        *,
        enabled: bool,
        hold_ms: int = 3000,
    ):
        preset = 5000 if hold_ms >= 5000 else 3000
        return self._queues.set_utterance_hold(
            session_id,
            enabled=enabled,
            hold_ms=preset,
        )

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

    def has_active_dialogue(self, session_id: str) -> bool:
        if self.is_pushing(session_id):
            return True
        if self.user_queue.has_pending(session_id):
            return True
        if self._compose_pending is not None and self._compose_pending(session_id):
            return True
        record = self.registry.get(session_id)
        if record.turn_index > 0 and not self.registry.is_temporally_expired(session_id):
            return True
        return False

    def inject_deferred_share_intents(self, session_id: str, intents) -> int:
        return self._queues.inject_deferred_share_intents(session_id, intents)

    def deferred_share_intents(self, session_id: str):
        return self._queues.deferred_share_intents(session_id)

    def pop_deferred_share_intent(self, session_id: str):
        return self._queues.pop_deferred_share_intent(session_id)

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
        self._social.on_user_message(session_id)
        return self._queues.submit_user_input(
            session_id,
            user_text,
            stream=stream,
            mode=mode,
            record=record,
        )

    def on_turn_complete(
        self,
        session_id: str,
        *,
        mode: str,
        session_state: str,
        answer: str,
    ) -> None:
        self._social.on_turn_complete(
            session_id,
            mode=mode,
            session_state=session_state,
            answer=answer,
        )

    def pop_pending_user_input(self, session_id: str) -> UserInputItem | None:
        return self._queues.pop_pending_user_input(session_id)

    def begin_push(self, session_id: str, user_text: str) -> None:
        self._queues.begin_push(session_id, user_text)

    def update_partial_output(self, session_id: str, partial: str) -> None:
        self._queues.update_partial_output(session_id, partial)

    def end_push(self, session_id: str, *, partial_output: str = "") -> InterruptContext | None:
        return self._queues.end_push(session_id, partial_output=partial_output)

    def interrupt_context_for(self, session_id: str, item: UserInputItem) -> InterruptContext | None:
        return self._queues.interrupt_context_for(session_id, item)

    def begin_turn(self, session_id: str) -> int:
        return self.registry.begin_turn(session_id)


SpeakSessionManager = SpeakSessionService
