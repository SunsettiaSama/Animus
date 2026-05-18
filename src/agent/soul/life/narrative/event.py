from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class NarrativeEventKind(str, Enum):
    """叙事引擎专用分类（人生弧 / 内心 / 创作 / 里程碑）。"""
    STORY_BEAT = "story_beat"
    THOUGHT = "thought"
    CREATIVE = "creative"
    MILESTONE = "milestone"


@dataclass
class NarrativeEvent:
    """叙事侧事实单元——仅在 ``life.narrative`` 包内使用，与 ledger 类型无共享。"""
    ts: str
    kind: NarrativeEventKind
    description: str
    source: str = ""
    duration_min: int = 0
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @staticmethod
    def now(
        kind: NarrativeEventKind,
        description: str,
        source: str = "",
        duration_min: int = 0,
        **metadata,
    ) -> NarrativeEvent:
        return NarrativeEvent(
            ts=datetime.now(timezone.utc).isoformat(),
            kind=kind,
            description=description,
            source=source,
            duration_min=duration_min,
            metadata=metadata,
        )

    def to_fact_line(self) -> str:
        prefix = f"[{self.kind.value}]"
        suffix = f"（{self.duration_min}分钟）" if self.duration_min > 0 else ""
        return f"{prefix} {self.description}{suffix}"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ts": self.ts,
            "kind": self.kind.value,
            "description": self.description,
            "source": self.source,
            "duration_min": self.duration_min,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> NarrativeEvent:
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            ts=d.get("ts", ""),
            kind=NarrativeEventKind(d.get("kind", "story_beat")),
            description=d.get("description", ""),
            source=d.get("source", ""),
            duration_min=int(d.get("duration_min", 0)),
            metadata=d.get("metadata", {}),
        )
