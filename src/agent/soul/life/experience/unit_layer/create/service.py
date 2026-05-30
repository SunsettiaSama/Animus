from __future__ import annotations

from agent.soul.life.experience.domain.unit import ExperienceUnit
from agent.soul.memory.io.session import DialogueCompressionBlock

from .from_compression_block import build_unit_from_compression


class UnitCreateService:
    """单元创建：静态块构造；Skill1 编写见 ``experience.skills``。"""

    def from_compression_block(
        self,
        block: DialogueCompressionBlock,
        *,
        interactor_id: str = "",
    ) -> ExperienceUnit:
        return build_unit_from_compression(block, interactor_id=interactor_id)
