from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SoulChannel(str, Enum):
    api = "api"
    tao = "tao"


class SoulDomain(str, Enum):
    life = "life"
    memory = "memory"
    persona = "persona"
    speak = "speak"


@dataclass(frozen=True)
class SoulRequest:
    """Soul 顶层请求：channel + domain + action + payload。"""

    domain: SoulDomain
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    channel: SoulChannel = SoulChannel.api
