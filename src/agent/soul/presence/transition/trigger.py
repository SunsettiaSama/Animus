from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..fsm.events import PresenceEvent
from ..fsm.state import PresenceContext
from .dialogue.block import DialogueBlock
from .incident.event import LifeIncident
from .init.wake import WakeContext
from .rumination.event import RuminationSignal


class PresenceTriggerKind(str, Enum):
    """transition 层统一触发类型。"""

    boundary = "boundary"
    dialogue = "dialogue"
    incident = "incident"
    rumination = "rumination"
    wake = "wake"
    sleep = "sleep"


@dataclass(frozen=True)
class PresenceTrigger:
    """统一触发载荷：由 PresenceTransitionEngine 路由到各子转移。"""

    kind: PresenceTriggerKind
    session_id: str
    boundary_event: PresenceEvent | None = None
    context: PresenceContext | None = None
    dialogue_block: DialogueBlock | None = None
    incident: LifeIncident | None = None
    rumination: RuminationSignal | None = None
    wake_context: WakeContext | None = None
    wake_force: bool = False

    @staticmethod
    def boundary(
        event: PresenceEvent,
        *,
        context: PresenceContext | None = None,
    ) -> PresenceTrigger:
        return PresenceTrigger(
            kind=PresenceTriggerKind.boundary,
            session_id=event.session_id,
            boundary_event=event,
            context=context,
        )

    @staticmethod
    def dialogue(
        session_id: str,
        *,
        user_text: str,
        agent_text: str,
    ) -> PresenceTrigger:
        return PresenceTrigger(
            kind=PresenceTriggerKind.dialogue,
            session_id=session_id,
            dialogue_block=DialogueBlock(user_text=user_text, agent_text=agent_text),
        )

    @staticmethod
    def incident(incident: LifeIncident) -> PresenceTrigger:
        return PresenceTrigger(
            kind=PresenceTriggerKind.incident,
            session_id=incident.session_id,
            incident=incident,
        )

    @staticmethod
    def rumination(rumination: RuminationSignal) -> PresenceTrigger:
        return PresenceTrigger(
            kind=PresenceTriggerKind.rumination,
            session_id=rumination.session_id,
            rumination=rumination,
        )

    @staticmethod
    def wake(
        session_id: str = "tao",
        *,
        context: WakeContext | None = None,
        force: bool = False,
    ) -> PresenceTrigger:
        return PresenceTrigger(
            kind=PresenceTriggerKind.wake,
            session_id=session_id,
            wake_context=context,
            wake_force=force,
        )

    @staticmethod
    def sleep(session_id: str = "tao") -> PresenceTrigger:
        return PresenceTrigger(
            kind=PresenceTriggerKind.sleep,
            session_id=session_id,
        )

    @property
    def label(self) -> str:
        if self.kind == PresenceTriggerKind.boundary and self.boundary_event is not None:
            return self.boundary_event.kind.value
        if self.kind == PresenceTriggerKind.incident and self.incident is not None:
            trigger = self.incident.trigger.strip()
            return trigger or self.incident.kind.value
        if self.kind == PresenceTriggerKind.rumination and self.rumination is not None:
            return self.rumination.trigger.strip() or "memory_ruminate"
        return self.kind.value
