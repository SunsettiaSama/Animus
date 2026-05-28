from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.life.experience.anchor_codec import read_anchor_context
from agent.soul.life.experience.sources import ExperienceSource
from agent.soul.life.experience.unit import ExperienceUnit

if TYPE_CHECKING:
    from agent.soul.memory.networks.event.service import EventMemoryNetwork
    from agent.soul.memory.networks.social.service import SocialMemoryNetwork


class LifeIngestAdapter:
    """L7：按 ExperienceSource 路由至 social / event 网络。"""

    def __init__(
        self,
        event: EventMemoryNetwork,
        social: SocialMemoryNetwork,
    ) -> None:
        self._event = event
        self._social = social

    def ingest_experience(self, unit: ExperienceUnit) -> None:
        source = unit.source
        if source == ExperienceSource.interaction.value:
            interactor_id = self._resolve_interactor_id(unit)
            self._social.ingest_interaction(unit, interactor_id=interactor_id)
            return
        self._event.ingest_experience(unit)

    def retract_experience(self, life_event_id: str) -> bool:
        return self._event.retract_experience(life_event_id)

    @staticmethod
    def _resolve_interactor_id(unit: ExperienceUnit) -> str:
        ctx = read_anchor_context(unit)
        if ctx is not None:
            interactor = getattr(ctx, "interactor_id", "") or ""
            if interactor.strip():
                return interactor.strip()
            session_id = ctx.session_id.strip()
            if session_id:
                return session_id
        return unit.situation.session_id.strip() or unit.id[:8]
