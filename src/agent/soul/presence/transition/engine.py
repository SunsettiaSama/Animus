from __future__ import annotations

from dataclasses import dataclass, field

from ..fsm.state import PresenceContext, PresenceState
from .apply import TransitionResult, apply_transition
from .dialogue import (
    DialogueFsmRefresher,
    DialogueObserveResult,
    DialogueSessionTransition,
)
from .incident import (
    IncidentFsmRefresher,
    IncidentIngestResult,
    IncidentTransition,
)
from .init import PresenceWakeEngine, SleepResult, WakeResult, apply_sleep
from .interaction import PresenceInteraction
from .rumination import (
    RuminationFsmRefresher,
    RuminationIngestResult,
    RuminationTransition,
)
from .trigger import PresenceTrigger, PresenceTriggerKind


@dataclass
class PresenceTransitionOutcome:
    """统一转移结果：保留各子路径的原始结果。"""

    trigger: PresenceTrigger
    applied: bool
    notes: list[str] = field(default_factory=list)
    boundary: TransitionResult | None = None
    dialogue: DialogueObserveResult | None = None
    incident: IncidentIngestResult | None = None
    rumination: RuminationIngestResult | None = None
    wake: WakeResult | None = None
    sleep: SleepResult | None = None


@dataclass
class PresenceTransitionEngine:
    """transition 顶层调度器：按 PresenceTrigger 路由到各子转移。"""

    dialogue: DialogueSessionTransition = field(default_factory=DialogueSessionTransition)
    incident: IncidentTransition = field(default_factory=IncidentTransition)
    rumination: RuminationTransition = field(default_factory=RuminationTransition)
    wake_engine: PresenceWakeEngine = field(default_factory=PresenceWakeEngine)

    @classmethod
    def from_refreshers(
        cls,
        *,
        dialogue_transition: DialogueSessionTransition | None = None,
        dialogue_refresher: DialogueFsmRefresher | None = None,
        incident_transition: IncidentTransition | None = None,
        incident_refresher: IncidentFsmRefresher | None = None,
        rumination_transition: RuminationTransition | None = None,
        rumination_refresher: RuminationFsmRefresher | None = None,
        wake_engine: PresenceWakeEngine | None = None,
    ) -> PresenceTransitionEngine:
        if dialogue_transition is not None:
            dialogue = dialogue_transition
        elif dialogue_refresher is not None:
            dialogue = DialogueSessionTransition(refresher=dialogue_refresher)
        else:
            dialogue = DialogueSessionTransition()

        if incident_transition is not None:
            incident = incident_transition
        elif incident_refresher is not None:
            incident = IncidentTransition(refresher=incident_refresher)
        else:
            incident = IncidentTransition()

        if rumination_transition is not None:
            rumination = rumination_transition
        elif rumination_refresher is not None:
            rumination = RuminationTransition(refresher=rumination_refresher)
        else:
            rumination = RuminationTransition()

        return cls(
            dialogue=dialogue,
            incident=incident,
            rumination=rumination,
            wake_engine=wake_engine or PresenceWakeEngine(),
        )

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
            result = apply_transition(state, interaction, event, ctx)
            return PresenceTransitionOutcome(
                trigger=trigger,
                applied=True,
                boundary=result,
                notes=list(result.notes),
            )

        if kind == PresenceTriggerKind.dialogue:
            block = trigger.dialogue_block
            if block is None:
                raise ValueError("dialogue trigger requires dialogue_block")
            result = self.dialogue.observe(state, block, session_id=sid)
            return PresenceTransitionOutcome(
                trigger=trigger,
                applied=result.counted,
                dialogue=result,
                notes=list(result.notes),
            )

        if kind == PresenceTriggerKind.incident:
            incident = trigger.incident
            if incident is None:
                raise ValueError("incident trigger requires incident")
            result = self.incident.ingest(
                state,
                incident,
                interaction=interaction,
            )
            return PresenceTransitionOutcome(
                trigger=trigger,
                applied=result.applied,
                incident=result,
                notes=list(result.notes),
            )

        if kind == PresenceTriggerKind.rumination:
            rumination = trigger.rumination
            if rumination is None:
                raise ValueError("rumination trigger requires rumination")
            result = self.rumination.ingest(
                state,
                rumination,
                interaction=interaction,
            )
            return PresenceTransitionOutcome(
                trigger=trigger,
                applied=result.applied,
                rumination=result,
                notes=list(result.notes),
            )

        if kind == PresenceTriggerKind.wake:
            ctx = trigger.wake_context or WakeContext()
            result = self.wake_engine.wake(state, session_id=sid, context=ctx)
            return PresenceTransitionOutcome(
                trigger=trigger,
                applied=result.applied,
                wake=result,
                notes=list(result.notes),
            )

        if kind == PresenceTriggerKind.sleep:
            result = apply_sleep(state, interaction, session_id=sid)
            return PresenceTransitionOutcome(
                trigger=trigger,
                applied=result.applied,
                sleep=result,
                notes=[result.reason] if result.reason else [],
            )

        raise ValueError(f"unsupported trigger kind: {kind.value}")
