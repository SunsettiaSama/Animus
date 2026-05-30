from __future__ import annotations

from .create import UnitCreateService
from .manage import (
    ExperienceCollapser,
    ExperienceLog,
    ExperienceOrchestrator,
    ExperienceUnitManager,
    NullCollapser,
)
from . import promote
from .promote.ports import MemoryIngestPort
from config.soul.presence.config import EXPERIENCE_MEMORY_INGEST_THRESHOLD

__all__ = [
    "ExperienceUnitLayer",
    "ExperienceUnitManager",
    "ExperienceOrchestrator",
    "MemoryIngestPort",
    "UnitCreateService",
    "promote",
]


class ExperienceUnitLayer:
    """体验单元管理层。

    数据流（擢升）
    ------------
    Inbound（Speak 蒸馏块 / 对话闭合 / 生活事件）
      → ``create``   构造 ``ExperienceUnit``（静态块 / Skill1）
      → ``manage``   热日志 JSONL、Chronicle 路由、交会折叠
      → ``promote``  ``promote_unit_to_memory``
      → ``life.io.memory.LifeExperienceMemoryIO``
      → ``memory.io.life.LifeMemoryIO.submit_experience``
      → ``memory.io.life.channel`` → ExperienceGraphIngest（图节点加工在 Memory 域）
    """

    def __init__(
        self,
        life_dir: str,
        *,
        memory_port: MemoryIngestPort | None = None,
        anchor_chronicle=None,
        virtual_chronicle=None,
        collapser: ExperienceCollapser | None = None,
        memory_ingest_threshold: float = EXPERIENCE_MEMORY_INGEST_THRESHOLD,
    ) -> None:
        self.log = ExperienceLog(life_dir)
        self.manage = ExperienceUnitManager(
            log=self.log,
            memory_port=memory_port,
            anchor_chronicle=anchor_chronicle,
            virtual_chronicle=virtual_chronicle,
            memory_ingest_threshold=memory_ingest_threshold,
            collapser=collapser,
        )
        self.create = UnitCreateService()
        self.promote = promote

    @property
    def orchestrator(self) -> ExperienceUnitManager:
        return self.manage
