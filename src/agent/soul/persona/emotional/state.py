from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

_FILENAME = "emotional_state.json"
_MAX_ANCHORS = 10  # compress into texture once we exceed this


@dataclass
class EmotionalAnchor:
    ts: str
    event: str
    felt: str

    def to_dict(self) -> dict:
        return {"ts": self.ts, "event": self.event, "felt": self.felt}

    @classmethod
    def from_dict(cls, d: dict) -> EmotionalAnchor:
        return cls(ts=d.get("ts", ""), event=d.get("event", ""), felt=d.get("felt", ""))


@dataclass
class EmotionalState:
    updated_at: str = ""
    texture: str = ""
    anchors: list[EmotionalAnchor] = field(default_factory=list)

    def render(self) -> str:
        parts = []
        if self.texture:
            parts.append(self.texture)
        for anchor in self.anchors[-3:]:
            parts.append(f"[{anchor.ts[:10]}] {anchor.event} → {anchor.felt}")
        return "\n".join(parts)

    def is_empty(self) -> bool:
        return not self.texture and not self.anchors

    def to_dict(self) -> dict:
        return {
            "updated_at": self.updated_at,
            "texture": self.texture,
            "anchors": [a.to_dict() for a in self.anchors],
        }

    @classmethod
    def from_dict(cls, d: dict) -> EmotionalState:
        return cls(
            updated_at=d.get("updated_at", ""),
            texture=d.get("texture", ""),
            anchors=[EmotionalAnchor.from_dict(a) for a in d.get("anchors", [])],
        )


class EmotionalStateStore:
    def __init__(self, persona_dir: str) -> None:
        self._path = Path(persona_dir) / _FILENAME

    def load(self) -> EmotionalState:
        if not self._path.exists():
            return EmotionalState()
        with open(self._path, encoding="utf-8") as f:
            return EmotionalState.from_dict(json.load(f))

    def save(self, state: EmotionalState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)

    def clear(self) -> None:
        if self._path.exists():
            os.remove(self._path)
