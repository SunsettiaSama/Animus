from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from agent.soul.speak.pipelines.types import (
    DEFAULT_SPEAK_PIPELINE,
    SpeakPipelineName,
    normalize_speak_pipeline,
)

from .share import SessionShareQueue
from ..pacing import SessionUtterancePacing, UtteranceHoldPreset
from .types import BrewLine, InterruptContext, SessionRuntime, SubmitUserInputResult, SpeakTurnMode
from .user import SessionUserQueue, UserInputItem

if TYPE_CHECKING:
    from agent.soul.speak.pipelines.request_driven.orchestrator.queue.hub import ComposeQueueHub


class SessionQueueHub:
    """会话推送态：user 队列、typing/brew、插队信号（compose 调度在 orchestrator）。"""

    def __init__(
        self,
        *,
        brew_queue_max: int = 3,
        typing_idle_ms: int = 3000,
    ) -> None:
        self._user_queue = SessionUserQueue()
        self._brew_queue_max = max(1, brew_queue_max)
        self._typing_idle_ms_default = max(500, typing_idle_ms)
        self._share_queue = SessionShareQueue()
        self._runtimes: dict[str, SessionRuntime] = {}
        self._compose_hub: ComposeQueueHub | None = None
        self._on_typing_start: Callable[[str], None] | None = None
        self._on_typing_idle: Callable[[str], None] | None = None

    def bind_compose_hub(self, compose_hub: ComposeQueueHub) -> None:
        self._compose_hub = compose_hub

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
        pipeline: SpeakPipelineName = DEFAULT_SPEAK_PIPELINE,
    ) -> None:
        runtime = self._runtime(session_id)
        with runtime.lock:
            runtime.pending_stream = stream
            runtime.pending_record = record
            runtime.pending_mode = mode
            runtime.pending_pipeline = pipeline

    def pop_pending_turn(
        self,
        session_id: str,
    ) -> tuple[str, bool, bool, SpeakTurnMode, SpeakPipelineName] | None:
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
                runtime.pending_pipeline,
            )
            runtime.pending_user_text = ""
            runtime.pending_stream = False
            runtime.pending_pipeline = DEFAULT_SPEAK_PIPELINE
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
    def user_queue(self) -> SessionUserQueue:
        return self._user_queue

    @property
    def share_queue(self) -> SessionShareQueue:
        return self._share_queue

    def inject_deferred_share_intents(self, session_id: str, intents) -> int:
        return self._share_queue.enqueue_batch(session_id, intents)

    def deferred_share_intents(self, session_id: str):
        return self._share_queue.as_intent_queue(session_id)

    def pop_deferred_share_intent(self, session_id: str):
        return self._share_queue.pop_most_wanted(session_id)

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
        pipeline: str | None = None,
    ) -> SubmitUserInputResult:
        typed_mode: SpeakTurnMode = "inbound" if mode == "inbound" else "proactive"
        selected_pipeline = normalize_speak_pipeline(pipeline)
        normalized = user_text.strip()
        if not normalized:
            return SubmitUserInputResult(notes=["session: empty user input"])

        runtime = self._runtime(session_id)
        interrupt_ctx: InterruptContext | None = None
        decision_token = 0
        with runtime.lock:
            if runtime.phase == "pushing":
                suspended_count = 0
                suspended_summary = ""
                if self._compose_hub is not None:
                    suspended_count, suspended_summary = self._compose_hub.suspend_session(
                        session_id,
                    )
                runtime.interrupt = InterruptContext(
                    new_user_text=normalized,
                    previous_user_text=runtime.active_user_text,
                    partial_agent_output=runtime.partial_agent_output,
                    suspended_compose_count=suspended_count,
                    suspended_compose_summary=suspended_summary,
                )
                if self._compose_hub is not None:
                    decision_token = self._compose_hub.begin_queue_decision(session_id)
                interrupt_ctx = runtime.interrupt
                self._user_queue.push_front(
                    UserInputItem(
                        session_id=session_id,
                        user_text=normalized,
                        mode=typed_mode,
                        stream=stream,
                        record=record,
                        pipeline=selected_pipeline,
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
                        pipeline=selected_pipeline,
                    ),
                )
                return SubmitUserInputResult(
                    queued=True,
                    notes=["session: user input queued"],
                )
            else:
                return SubmitUserInputResult(queued=False)

        if interrupt_ctx is not None and self._compose_hub is not None:
            self._compose_hub.request_queue_decision(session_id, interrupt_ctx, decision_token)
            self._compose_hub.schedule_compose(session_id, typed_mode)
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

    def interrupt_context_for(self, session_id: str, item: UserInputItem) -> InterruptContext | None:
        if not item.interrupted:
            return None
        runtime = self._runtime(session_id)
        with runtime.lock:
            if runtime.interrupt is not None:
                return runtime.interrupt
            suspended_count = 0
            suspended_summary = ""
            if self._compose_hub is not None:
                snap = self._compose_hub.debug_snapshot(session_id)
                suspended_count = int(snap.get("suspended_compose_count", 0))
            return InterruptContext(
                new_user_text=item.user_text,
                previous_user_text=runtime.partial_agent_output,
                suspended_compose_count=suspended_count,
                suspended_compose_summary=suspended_summary,
            )

    def debug_snapshot(self, session_id: str) -> dict[str, object]:
        runtime = self._runtimes.get(session_id)
        phase = "idle"
        partial = ""
        if runtime is not None:
            with runtime.lock:
                phase = runtime.phase
                partial = runtime.partial_agent_output
        out: dict[str, object] = {
            "session_id": session_id,
            "push_phase": phase,
            "partial_agent_output_chars": len(partial),
            "partial_agent_output_preview": partial[:300],
            "share_queue": self._share_queue.peek_session(session_id),
            "user_queue_pending": self._user_queue.has_pending(session_id),
        }
        if self._compose_hub is not None:
            out.update(self._compose_hub.debug_snapshot(session_id))
        return out

    def clear_session(self, session_id: str) -> None:
        self._share_queue.clear_session(session_id)
        runtime = self._runtimes.pop(session_id, None)
        if runtime is not None:
            with runtime.lock:
                if runtime.idle_timer is not None:
                    runtime.idle_timer.cancel()
                    runtime.idle_timer = None
                runtime.interrupt = None
                runtime.brew_queue.clear()
                runtime.pending_user_text = ""
        self._user_queue.clear_session(session_id)
