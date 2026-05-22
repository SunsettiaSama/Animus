from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AffectAnchor:
    """单条主观情绪事件（Drive 状态机附属字段）。"""

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
    """Drive FSM 附属：快变情绪质感 + 近期锚点。"""

    updated_at: str = ""
    texture: str = ""
    anchors: list[AffectAnchor] = field(default_factory=list)

    def render(self) -> str:
        parts: list[str] = []
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
    def from_dict(cls, d: dict) -> AffectState:
        return cls(
            updated_at=d.get("updated_at", ""),
            texture=d.get("texture", ""),
            anchors=[AffectAnchor.from_dict(a) for a in d.get("anchors", [])],
        )

    def copy(self) -> AffectState:
        return AffectState(
            updated_at=self.updated_at,
            texture=self.texture,
            anchors=list(self.anchors),
        )


# 兼容 self_concept / heartbeat 既有命名
EmotionalAnchor = AffectAnchor
