from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SpeakPersonaInjected:
    """人格层外部注入：画像与自我认知，compose 周期内视为稳定。"""

    traits: str = ""
    self_concept: str = ""

    def render_blocks(self) -> list[str]:
        return [block.strip() for block in (self.traits, self.self_concept) if block.strip()]
