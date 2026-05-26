from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from agent.soul.life.anchor.presence_bundle import PresenceExperienceBundle

from ..state import PresenceContext, PresenceEvent
from .static.lifecycle import WakeContext


class PresenceTriggerKind(str, Enum):
    boundary = "boundary"
    wake = "wake"
    sleep = "sleep"
    life_sync = "life_sync"
    inject = "inject"


@dataclass(frozen=True)
class PresenceTrigger:
    kind: PresenceTriggerKind
    session_id: str
    boundary_event: PresenceEvent | None = None
    context: PresenceContext | None = None
    wake_context: WakeContext | None = None
    wake_force: bool = False
    life_bundle: PresenceExperienceBundle | None = None
    payload: object = None

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

    @staticmethod
    def life_sync(
        bundle: PresenceExperienceBundle,
    ) -> PresenceTrigger:
        return PresenceTrigger(
            kind=PresenceTriggerKind.life_sync,
            session_id=bundle.session_id,
            life_bundle=bundle,
        )

    @property
    def label(self) -> str:
        if self.kind == PresenceTriggerKind.boundary and self.boundary_event is not None:
            return self.boundary_event.kind.value
        return self.kind.value
