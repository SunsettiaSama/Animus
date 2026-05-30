from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agent.soul.memory.emergence import Emergence
from agent.soul.memory.graph.networks.social.network import SocialMemoryNetwork
from config.soul.memory.service_config import MemoryServiceConfig


@dataclass
class SessionIODeps:
    """Session IO 检索依赖（由 MemoryService 注入，避免子模块直连）。"""

    social: SocialMemoryNetwork
    emergence: Emergence
    cfg: MemoryServiceConfig
    resolve_channel_interactor: Callable[[str], str]
    bind_session_channel: Callable[[str, str], None]
    enqueue_write: Callable[[Callable[[], None]], None]
