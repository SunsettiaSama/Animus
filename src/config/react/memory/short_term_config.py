from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ShortTermMemoryConfig:
    max_turns: int = 10
    max_tokens: int = 2048
