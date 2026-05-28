"""Backward-compatible entry — implementation in ``facade``."""

from agent.soul.memory.facade.build import build_memory_service
from agent.soul.memory.facade.service import MemoryService
from agent.soul.memory.networks.event.service import MemoryBlock

MemoryService.build = staticmethod(build_memory_service)

__all__ = ["MemoryBlock", "MemoryService"]
