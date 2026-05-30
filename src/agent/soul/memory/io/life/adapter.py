from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.life.experience.domain.unit import ExperienceUnit
from .request import (
    DialogueCloseInbound,
    ExperienceIngestInbound,
    ExperienceRetractInbound,
)

if TYPE_CHECKING:
    from .gateway import LifeMemoryIO


class LifeMemoryPortAdapter:
    """Life 编排器 MemoryIngestPort 适配：全部委托 LifeMemoryIO。"""

    def __init__(self, io: LifeMemoryIO) -> None:
        self._io = io

    def ingest_experience(self, unit: ExperienceUnit) -> None:
        from agent.soul.life.io.memory import LifeExperienceMemoryIO

        LifeExperienceMemoryIO(self._io).promote_unit(unit)

    def retract_experience(self, life_event_id: str) -> bool:
        return self._io.retract_experience(
            ExperienceRetractInbound(life_event_id=life_event_id),
        )

    def close_dialogue_session(
        self,
        session_id: str,
        *,
        interactor_id: str = "",
        final_unit: ExperienceUnit | None = None,
    ) -> None:
        from agent.soul.life.io.memory import LifeExperienceMemoryIO

        LifeExperienceMemoryIO(self._io).close_dialogue_session(
            session_id,
            interactor_id=interactor_id,
            final_unit=final_unit,
        )


def as_life_memory_port(io: LifeMemoryIO):
    return LifeMemoryPortAdapter(io)
