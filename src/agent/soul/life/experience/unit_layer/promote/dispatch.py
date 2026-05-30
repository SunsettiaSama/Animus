from __future__ import annotations

from agent.soul.life.experience.domain.unit import ExperienceUnit

from .ports import MemoryIngestPort


def promote_unit_to_memory(memory_port: MemoryIngestPort, unit: ExperienceUnit) -> None:
    """单元擢升：Experience → life.io.memory → memory.io.life → ExperienceGraphIngest。"""
    memory_port.ingest_experience(unit)
