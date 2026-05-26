from __future__ import annotations

from dataclasses import dataclass, field

from agent.soul.life.anchor.presence_bundle import PresenceExperienceBundle

from ..state import PresenceContext, PresenceEvent, PresenceState
from .dynamic.boundary import TransitionResult, apply_boundary_transition
from .dynamic.life_meta import apply_dynamic_bundle
from .interaction import PresenceInteraction
from .ports import TransitionHandler, TransitionNotes
from .static.lifecycle import WakeContext, WakeResult, SleepResult, apply_sleep, apply_wake
from .static.life_sync import apply_static_bundle
from .trigger import PresenceTrigger, PresenceTriggerKind


@dataclass
class LifeSyncTransitionResult:
    static_notes: list[str] = field(default_factory=list)
    dynamic_notes: list[str] = field(default_factory=list)
    bundle_source: str = ""


@dataclass
class PresenceTransitionOutcome:
    trigger: PresenceTrigger
    applied: bool
    notes: list[str] = field(default_factory=list)
    boundary: TransitionResult | None = None
    wake: WakeResult | None = None
    sleep: SleepResult | None = None
    life_sync: LifeSyncTransitionResult | None = None


class PresenceTransitionRouter:
    """顶层统一路由：static（五维自叙 + 生命周期）与 dynamic（FSM + 分享驱动）。"""

    def __init__(self) -> None:
        self._inject_handlers: dict[PresenceTriggerKind, TransitionHandler] = {}

    def register(self, kind: PresenceTriggerKind, handler: TransitionHandler) -> None:
        self._inject_handlers[kind] = handler

    def dispatch(
        self,
        trigger: PresenceTrigger,
        *,
        state: PresenceState,
        interaction: PresenceInteraction,
    ) -> PresenceTransitionOutcome:
        kind = trigger.kind
        sid = trigger.session_id

        if kind == PresenceTriggerKind.boundary:
            event = trigger.boundary_event
            if event is None:
                raise ValueError("boundary trigger requires boundary_event")
            ctx = trigger.context or PresenceContext()
            result = apply_boundary_transition(state, interaction, event, ctx)
            return PresenceTransitionOutcome(
                trigger=trigger,
                applied=True,
                boundary=result,
                notes=list(result.notes),
            )

        if kind == PresenceTriggerKind.wake:
            ctx = trigger.wake_context or WakeContext()
            result = apply_wake(
                state,
                interaction,
                session_id=sid,
                context=ctx,
            )
            return PresenceTransitionOutcome(
                trigger=trigger,
                applied=result.applied,
                wake=result,
                notes=list(result.notes or []),
            )

        if kind == PresenceTriggerKind.sleep:
            result = apply_sleep(state, interaction, session_id=sid)
            return PresenceTransitionOutcome(
                trigger=trigger,
                applied=result.applied,
                sleep=result,
                notes=[result.reason] if result.reason else [],
            )

        if kind == PresenceTriggerKind.life_sync:
            bundle = trigger.life_bundle
            if bundle is None:
                raise ValueError("life_sync trigger requires life_bundle")
            static_notes = apply_static_bundle(state, bundle)
            dynamic_notes = apply_dynamic_bundle(state, interaction, bundle)
            sync = LifeSyncTransitionResult(
                static_notes=static_notes,
                dynamic_notes=dynamic_notes,
                bundle_source=bundle.source,
            )
            return PresenceTransitionOutcome(
                trigger=trigger,
                applied=True,
                life_sync=sync,
                notes=static_notes + dynamic_notes,
            )

        handler = self._inject_handlers.get(kind)
        if handler is None:
            raise ValueError(f"no handler registered for trigger kind: {kind.value}")

        notes = handler.apply(
            session_id=sid,
            state=state,
            interaction=interaction,
            payload=trigger.payload,
        )
        return PresenceTransitionOutcome(
            trigger=trigger,
            applied=notes.applied,
            notes=list(notes.notes),
        )
