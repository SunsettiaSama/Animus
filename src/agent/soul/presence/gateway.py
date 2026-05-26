from __future__ import annotations

from typing import TYPE_CHECKING

from .gateway_result import GatewayResult
from .state import PresenceContext, PresenceEvent, PresenceEventKind
from .transition import (
    Expectation,
    PresenceTransitionOutcome,
    PresenceTrigger,
    PresenceTriggerKind,
    WakeContext,
    WakeResult,
    SleepResult,
)

if TYPE_CHECKING:
    from .service import PresenceIngestResult, PresenceService, PresenceSession, PresenceSnapshot


class PresenceGateway:
    """顶层入站：接收外部事件 → transition 分发（仅更新状态）。"""

    def __init__(self, service: PresenceService) -> None:
        self._svc = service

    def trigger(self, trigger: PresenceTrigger) -> GatewayResult:
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
                return GatewayResult(
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
            outcome = svc._transition_router.dispatch(
                wake_trigger,
                state=session.state,
                interaction=session.interaction,
            )
            session.awake = True
            session.last_wake_date = today
            session.state.expectation.share_queue.drain()
            session.interaction.reset()
            svc._persist(sid)
            svc._maybe_scan_expectation(sid)
            return GatewayResult(
                outcome=outcome,
                before=before,
                after=svc.snapshot(sid),
            )

        if trigger.kind == PresenceTriggerKind.sleep:
            if not session.awake and session.state.is_empty():
                sleep = SleepResult(session_id=sid, applied=False, reason="already asleep")
                return GatewayResult(
                    outcome=PresenceTransitionOutcome(
                        trigger=trigger,
                        applied=False,
                        sleep=sleep,
                        notes=[sleep.reason],
                    ),
                    before=before,
                    after=before,
                )
            outcome = svc._transition_router.dispatch(
                trigger,
                state=session.state,
                interaction=session.interaction,
            )
            session.awake = False
            session.state.expectation.share_queue.drain()
            svc._persist(sid)
            return GatewayResult(
                outcome=outcome,
                before=before,
                after=svc.snapshot(sid),
            )

        outcome = svc._transition_router.dispatch(
            trigger,
            state=session.state,
            interaction=session.interaction,
        )
        svc._persist(sid)
        return GatewayResult(
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

    def _trigger_boundary(
        self,
        trigger: PresenceTrigger,
        *,
        before: PresenceSnapshot,
    ) -> GatewayResult:
        svc = self._svc
        event = trigger.boundary_event
        if event is None:
            raise ValueError("boundary trigger requires boundary_event")
        sid = trigger.session_id
        session = svc._session(sid)
        ctx = trigger.context or PresenceContext()
        impulse_discharge = None
        flushed_on_external_start = False

        if event.kind == PresenceEventKind.user_text and not ctx.line_open:
            impulse_discharge = svc._discharge_session_accumulated(
                session_id=sid,
                session=session,
                source="external_start_flush",
                wait_reply=False,
                expectation=Expectation.none,
                require_saturated=False,
            )
            session.interaction.expectation = Expectation.none
            flushed_on_external_start = impulse_discharge is not None

        outcome = svc._transition_router.dispatch(
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

        svc._sessions[sid] = session
        svc._persist(sid)
        after = svc.snapshot(sid)

        return GatewayResult(
            outcome=outcome,
            before=before,
            after=after,
            boundary=True,
            buffered_share_count=len(session.state.expectation.share_queue),
            impulse_discharge=impulse_discharge,
        )

    def _boundary_ingest_from_trigger(
        self,
        result: GatewayResult,
    ) -> PresenceIngestResult:
        from .service import PresenceIngestResult

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
            boundary=True,
            buffered_share_count=result.buffered_share_count,
            impulse_discharge=result.impulse_discharge,
        )
