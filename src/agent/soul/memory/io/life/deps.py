from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from agent.soul.memory.graph.networks.event.network import EventMemoryNetwork
from agent.soul.memory.graph.networks.social.network import SocialMemoryNetwork
from agent.soul.memory.io.session.channel import SessionMemoryChannel
from agent.soul.memory.rumination import RuminationService

if TYPE_CHECKING:
    from infra.llm import BaseLLM


@dataclass
class LifeIODeps:
    """Life IO 依赖（由 MemoryService 注入）。"""

    event: EventMemoryNetwork
    social: SocialMemoryNetwork
    rumination: RuminationService
    session_compression: SessionMemoryChannel
    enqueue_write: Callable[[Callable[[], None]], None]
    agent_persona_narrative: Callable[[], str]
    llm: BaseLLM | None = None
