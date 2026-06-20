from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PersonaIdentityBlock:
    """稳定人格 + 自叙蒸馏：你是谁、你是怎样的人。"""

    narrative: str = ""
    stable_source: str = ""

    def render(self) -> str:
        return self.narrative.strip()
