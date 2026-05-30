from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.life.experience.domain.unit import ExperienceUnit
from agent.soul.memory.io.life.request import (
    ExperienceIngestInbound,
    ExperienceRetractInbound,
)

if TYPE_CHECKING:
    from agent.soul.memory.io.life.gateway import LifeMemoryIO


def _resolve_interactor_id(unit: ExperienceUnit) -> str:
    from agent.soul.life.experience.domain.anchor_codec import read_anchor_context

    ctx = read_anchor_context(unit)
    if ctx is not None and ctx.interactor_id.strip():
        return ctx.interactor_id.strip()
    return (unit.situation.session_id or "").strip()


class LifeExperienceMemoryIO:
    """Experience 编排器 → Memory 正式图（经 ``memory.io.life``，无会话 buffer）。"""

    def __init__(self, memory_io: LifeMemoryIO) -> None:
        self._memory_io = memory_io

    def promote_unit(self, unit: ExperienceUnit) -> None:
        """新体验单元：立即走 Skill2 路由 + 正式落图（异步 enqueue）。"""
        self._memory_io.submit_experience(
            ExperienceIngestInbound(
                unit=unit,
                interactor_id=_resolve_interactor_id(unit),
            ),
        )

    def ingest_experience(self, unit: ExperienceUnit) -> None:
        self.promote_unit(unit)

    def retract_experience(self, life_event_id: str) -> bool:
        return self._memory_io.retract_experience(
            ExperienceRetractInbound(life_event_id=life_event_id),
        )

    def close_dialogue_session(
        self,
        session_id: str,
        *,
        interactor_id: str = "",
        final_unit: ExperienceUnit | None = None,
    ) -> None:
        """会话闭合：仅擢升终局 ExperienceUnit（不再整合 SessionMemoryBuffer）。"""
        _ = session_id
        _ = interactor_id
        if final_unit is not None:
            self.promote_unit(final_unit)
