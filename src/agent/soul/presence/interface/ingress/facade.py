from __future__ import annotations

from typing import TYPE_CHECKING

from ...fsm import PresenceContext, PresenceEvent
from ...transition import (
    Expectation,
    PresenceTransitionOutcome,
    PresenceTrigger,
    PresenceTriggerKind,
    WakeContext,
    WakeResult,
    SleepResult,
)
from .capture import run_evolution_capture
from ..shared.events import CaptureEvent, CaptureKind
from .result import PresenceTriggerResult

if TYPE_CHECKING:
    from ...service import PresenceIngestResult, PresenceService, PresenceSession, PresenceSnapshot


class PresenceInterface:
    """ingress 入站门面：trigger / capture / boundary → transition + egress 门控。"""

    def __init__(self, service: PresenceService) -> None:
        self._svc = service

    def trigger(self, trigger: PresenceTrigger) -> PresenceTriggerResult:
        svc = self._svc
        sid = trigger.session_id
        session = svc._session(sid)
        before = svc.snapshot(sid)

        if trigger.kind == PresenceTriggerKind.boundary:
            return self._trigger_boundary(trigger, before=before)

        if trigger.kind == PresenceTriggerKind.wake:
            today = svc._today()
            if (
                not trigger.wake_force
                and session.awake
                and session.last_wake_date == today
            ):
                wake = WakeResult(
                    session_id=sid,
                    applied=False,
                    reason="already awake today",
                )
                return PresenceTriggerResult(
                    outcome=PresenceTransitionOutcome(
                        trigger=trigger,
                        applied=False,
                        wake=wake,
                        notes=[wake.reason],
                    ),
                    before=before,
                    after=before,
                )
            ctx = trigger.wake_context or WakeContext(timezone=svc._timezone)
            if trigger.wake_context is None or not trigger.wake_context.timezone:
                ctx = WakeContext(
                    agent_name=ctx.agent_name,
                    persona_summary=ctx.persona_summary,
                    self_narrative=ctx.self_narrative,
                    timezone=svc._timezone,
                )
            wake_trigger = PresenceTrigger.wake(sid, context=ctx, force=trigger.wake_force)
            outcome = svc._transition_engine.dispatch(
                wake_trigger,
                state=session.state,
                interaction=session.interaction,
            )
            session.awake = True
            session.last_wake_date = today
            session.state.expectation.share_queue.drain()
            session.interaction.reset()
            svc._dialogue_transition.reset_session(sid)
            svc._persist(sid)
            svc._maybe_scan_expectation(sid)
            return PresenceTriggerResult(
                outcome=outcome,
                before=before,
                after=svc.snapshot(sid),
            )

        if trigger.kind == PresenceTriggerKind.sleep:
            if not session.awake and session.state.is_empty():
                sleep = SleepResult(session_id=sid, applied=False, reason="already asleep")
                return PresenceTriggerResult(
                    outcome=PresenceTransitionOutcome(
                        trigger=trigger,
                        applied=False,
                        sleep=sleep,
                        notes=[sleep.reason],
                    ),
                    before=before,
                    after=before,
                )
            outcome = svc._transition_engine.dispatch(
                trigger,
                state=session.state,
                interaction=session.interaction,
            )
            session.awake = False
            session.state.expectation.share_queue.drain()
            svc._dialogue_transition.reset_session(sid)
            svc._persist(sid)
            return PresenceTriggerResult(
                outcome=outcome,
                before=before,
                after=svc.snapshot(sid),
            )

        outcome = svc._transition_engine.dispatch(
            trigger,
            state=session.state,
            interaction=session.interaction,
        )
        self._apply_trigger_side_effects(session, trigger, outcome)
        if self._should_persist_trigger(trigger, outcome):
            svc._persist(sid)
        return PresenceTriggerResult(
            outcome=outcome,
            before=before,
            after=svc.snapshot(sid),
        )

    def boundary(
        self,
        event: PresenceEvent,
        *,
        context: PresenceContext | None = None,
    ) -> PresenceIngestResult:
        result = self.trigger(PresenceTrigger.boundary(event, context=context))
        return self._boundary_ingest_from_trigger(result)

    def capture(self, event: CaptureEvent) -> PresenceIngestResult:
        return run_evolution_capture(self._svc, event, context=PresenceContext())

    def _trigger_boundary(
        self,
        trigger: PresenceTrigger,
        *,
        before: PresenceSnapshot,
    ) -> PresenceTriggerResult:
        svc = self._svc
        event = trigger.boundary_event
        if event is None:
            raise ValueError("boundary trigger requires boundary_event")
        sid = trigger.session_id
        session = svc._session(sid)
        ctx = trigger.context or PresenceContext()
        flushed_on_external_start = False

        if event.kind.value == CaptureKind.user_text.value and not ctx.line_open:
            svc._flush_session_accumulated(
                session_id=sid,
                session=session,
                source="external_start_flush",
                wait_reply=False,
                expectation=Expectation.none,
                require_saturated=False,
            )
            session.interaction.expectation = Expectation.none
            flushed_on_external_start = True

        outcome = svc._transition_engine.dispatch(
            trigger,
            state=session.state,
            interaction=session.interaction,
        )
        notes = (
            ["presence: flushed accumulated impulse on external start"]
            if flushed_on_external_start
            else []
        ) + list(outcome.notes)
        outcome = PresenceTransitionOutcome(
            trigger=trigger,
            applied=True,
            boundary=outcome.boundary,
            notes=notes,
        )

        speak_req = svc._egress.evaluate(
            session_id=sid,
            interaction=session.interaction,
            expectation=session.state.expectation,
        )
        if speak_req is not None:
            session.interaction.discharge_impulse(speak_req.impulse_level)
            session.state.expectation.share_queue.drain()
            if svc._on_speak_request is not None:
                svc._on_speak_request(speak_req)

        svc._sessions[sid] = session
        svc._persist(sid)
        after = svc.snapshot(sid)

        return PresenceTriggerResult(
            outcome=outcome,
            before=before,
            after=after,
            speak_request=speak_req,
            boundary=True,
            buffered_share_count=len(session.state.expectation.share_queue),
        )

    def _boundary_ingest_from_trigger(
        self,
        result: PresenceTriggerResult,
    ) -> PresenceIngestResult:
        from ...service import PresenceIngestResult

        event = result.trigger.boundary_event
        if event is None:
            raise ValueError("boundary trigger requires boundary_event")
        if result.before is None or result.after is None:
            raise RuntimeError("boundary trigger result missing snapshots")
        return PresenceIngestResult(
            before=result.before,
            after=result.after,
            event=event,
            notes=list(result.notes),
            speak_request=result.speak_request,
            boundary=True,
            buffered_share_count=result.buffered_share_count,
        )

    def _apply_trigger_side_effects(
        self,
        session: PresenceSession,
        trigger: PresenceTrigger,
        outcome: PresenceTransitionOutcome,
    ) -> None:
        svc = self._svc
        sid = trigger.session_id
        if trigger.kind == PresenceTriggerKind.dialogue and outcome.dialogue is not None:
            refresh = outcome.dialogue.refresh
            if outcome.dialogue.refreshed and refresh and refresh.dialogue_expectation is not None:
                session.interaction.expectation = refresh.dialogue_expectation
                if refresh.dialogue_expectation in (
                    Expectation.required,
                    Expectation.clarify,
                ):
                    session.state.expectation.accumulate_reply_urge(
                        0.25,
                        reason="dialogue follow-up",
                        source="dialogue",
                    )
            return

        if trigger.kind == PresenceTriggerKind.incident and outcome.applied:
            svc._maybe_scan_expectation(sid)
            return

        if trigger.kind == PresenceTriggerKind.rumination and outcome.applied:
            svc._maybe_scan_expectation(sid)

    def _should_persist_trigger(
        self,
        trigger: PresenceTrigger,
        outcome: PresenceTransitionOutcome,
    ) -> bool:
        if trigger.kind == PresenceTriggerKind.dialogue:
            return bool(outcome.dialogue and outcome.dialogue.refreshed)
        if trigger.kind in (
            PresenceTriggerKind.incident,
            PresenceTriggerKind.rumination,
        ):
            return outcome.applied
        return True
