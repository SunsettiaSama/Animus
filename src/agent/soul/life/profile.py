from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_FILENAME = "life_profile.json"


@dataclass
class LifeProfile:
    updated_at: str = ""
    narrative: str = ""
    world_id: str = ""

    def render(self) -> str:
        return self.narrative

    def is_empty(self) -> bool:
        return not self.narrative

    def resolved_world_id(self, default: str = "default") -> str:
        token = self.world_id.strip()
        return token or default

    def to_dict(self) -> dict:
        return {
            "updated_at": self.updated_at,
            "narrative": self.narrative,
            "world_id": self.world_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LifeProfile:
        return cls(
            updated_at=d.get("updated_at", ""),
            narrative=d.get("narrative", ""),
            world_id=str(d.get("world_id", "")).strip(),
        )


class LifeProfileStore:
    def __init__(self, life_dir: str) -> None:
        self._path = Path(life_dir) / _FILENAME

    def load(self) -> LifeProfile:
        if not self._path.exists():
            return LifeProfile()
        with open(self._path, encoding="utf-8") as f:
            return LifeProfile.from_dict(json.load(f))

    def save(self, profile: LifeProfile) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(profile.to_dict(), f, ensure_ascii=False, indent=2)
