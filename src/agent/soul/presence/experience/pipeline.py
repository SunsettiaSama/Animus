from __future__ import annotations

from typing import TYPE_CHECKING

from config.soul.presence.config import EXPERIENCE_MEMORY_INGEST_THRESHOLD

from .collapser import ExperienceCollapser
from .dialogue import DialogueExperiencePipeline
from .life import LifeExperiencePipeline
from .log import ExperienceLog
from .orchestrator import ExperienceOrchestrator, MemoryIngestPort

if TYPE_CHECKING:
    from agent.soul.life.anchor.chronicle import AnchorChronicleStore
    from agent.soul.life.virtual.chronicle import VirtualChronicleStore


class PresenceExperiencePipeline:
    """共享编排器 + 对话/生活两个子模块。"""

    def __init__(
        self,
        life_dir: str,
        *,
        memory_port: MemoryIngestPort | None = None,
        anchor_chronicle: AnchorChronicleStore | None = None,
        virtual_chronicle: VirtualChronicleStore | None = None,
        collapser: ExperienceCollapser | None = None,
        memory_ingest_threshold: float = EXPERIENCE_MEMORY_INGEST_THRESHOLD,
    ) -> None:
        self.log = ExperienceLog(life_dir)
        self.orchestrator = ExperienceOrchestrator(
            log=self.log,
            memory_port=memory_port,
            anchor_chronicle=anchor_chronicle,
            virtual_chronicle=virtual_chronicle,
            memory_ingest_threshold=memory_ingest_threshold,
        )
        if collapser is not None:
            self.orchestrator.set_collapser(collapser)
        self.dialogue = DialogueExperiencePipeline(orchestrator=self.orchestrator)
        self.life = LifeExperiencePipeline(
            orchestrator=self.orchestrator,
            log=self.log,
        )
