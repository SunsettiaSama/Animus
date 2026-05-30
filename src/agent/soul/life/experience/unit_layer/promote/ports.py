from __future__ import annotations

from typing import Protocol

from agent.soul.life.experience.domain.unit import ExperienceUnit


class MemoryIngestPort(Protocol):
    """Experience 擢升出站协议 → ``life.io.memory.LifeExperienceMemoryIO`` 实现。"""

    def ingest_experience(self, unit: ExperienceUnit) -> None: ...

    def retract_experience(self, life_event_id: str) -> bool: ...

    def close_dialogue_session(
        self,
        session_id: str,
        *,
        interactor_id: str = "",
        final_unit: ExperienceUnit | None = None,
    ) -> None: ...
