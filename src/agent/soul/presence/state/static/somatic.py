from __future__ import annotations

from dataclasses import dataclass

from .narrative import normalize_narrative


@dataclass
class SomaticState:
    """生理状态：第一人称自叙。"""

    narrative: str = ""

    def render(self) -> str:
        return normalize_narrative(self.narrative)

    def is_empty(self) -> bool:
        return not self.render()

    def copy(self) -> SomaticState:
        return SomaticState(narrative=self.narrative)

    def to_dict(self) -> dict:
        return {"narrative": self.narrative}

    @classmethod
    def from_dict(cls, d: dict) -> SomaticState:
        if "narrative" in d:
            return cls(narrative=str(d.get("narrative", "")))
        sensation = normalize_narrative(str(d.get("sensation", "")))
        return cls(narrative=sensation)
