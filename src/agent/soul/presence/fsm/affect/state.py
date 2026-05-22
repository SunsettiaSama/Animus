from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AffectAnchor:
    """单条主观情绪事件。"""

    ts: str
    event: str
    felt: str

    def to_dict(self) -> dict:
        return {"ts": self.ts, "event": self.event, "felt": self.felt}

    @classmethod
    def from_dict(cls, d: dict) -> AffectAnchor:
        return cls(ts=d.get("ts", ""), event=d.get("event", ""), felt=d.get("felt", ""))


@dataclass
class AffectState:
    """情绪与感受：效价、强度、质感与近期锚点。"""

    updated_at: str = ""
    texture: str = ""
    valence: str = ""
    intensity: float = 0.0
    anchors: list[AffectAnchor] = field(default_factory=list)

    def render(self) -> str:
        parts: list[str] = []
        if self.texture:
            parts.append(self.texture)
        for anchor in self.anchors[-3:]:
            parts.append(f"[{anchor.ts[:10]}] {anchor.event} → {anchor.felt}")
        return "\n".join(parts)

    def is_empty(self) -> bool:
        return not self.texture and not self.anchors and not self.valence

    def copy(self) -> AffectState:
        return AffectState(
            updated_at=self.updated_at,
            texture=self.texture,
            valence=self.valence,
            intensity=self.intensity,
            anchors=list(self.anchors),
        )

    def to_dict(self) -> dict:
        return {
            "updated_at": self.updated_at,
            "texture": self.texture,
            "valence": self.valence,
            "intensity": self.intensity,
            "anchors": [a.to_dict() for a in self.anchors],
        }

    @classmethod
    def from_dict(cls, d: dict) -> AffectState:
        return cls(
            updated_at=d.get("updated_at", ""),
            texture=d.get("texture", ""),
            valence=d.get("valence", ""),
            intensity=float(d.get("intensity", 0.0)),
            anchors=[AffectAnchor.from_dict(a) for a in d.get("anchors", [])],
        )


EmotionalAnchor = AffectAnchor
