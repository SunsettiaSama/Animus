from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.soul.life.experience.unit import ExperienceUnit


class LedgerEventKind(str, Enum):
    """Tao / 交互账本专用分类（与用户对话及会话周边任务）。"""
    TAO_DIALOGUE = "tao_dialogue"
    INTERACTION = "interaction"
    TASK = "task"


@dataclass
class LedgerEvent:
    """交互侧事实单元——仅在 ``life.ledger`` 包内使用，与叙事事件类型无共享。"""
    ts: str
    kind: LedgerEventKind
    description: str
    source: str = ""
    duration_min: int = 0
    metadata: dict = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    @staticmethod
    def now(
        kind: LedgerEventKind,
        description: str,
        source: str = "",
        duration_min: int = 0,
        **metadata,
    ) -> LedgerEvent:
        return LedgerEvent(
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
    def from_dict(cls, d: dict) -> LedgerEvent:
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            ts=d.get("ts", ""),
            kind=LedgerEventKind(d.get("kind", "tao_dialogue")),
            description=d.get("description", ""),
            source=d.get("source", ""),
            duration_min=int(d.get("duration_min", 0)),
            metadata=d.get("metadata", {}),
        )

    def to_experience_unit(self, turn_index: int = 0) -> ExperienceUnit:
        from agent.soul.life.experience.unit import (
            ExperienceAction,
            ExperienceActionKind,
            ExperienceFeeling,
            ExperienceSituation,
            ExperienceUnit,
        )
        _kind_map = {
            LedgerEventKind.TAO_DIALOGUE: ExperienceActionKind.speaking,
            LedgerEventKind.INTERACTION:  ExperienceActionKind.attending,
            LedgerEventKind.TASK:         ExperienceActionKind.tool_use,
        }
        return ExperienceUnit(
            id=self.id,
            ts=self.ts,
            source="user",
            situation=ExperienceSituation(
                session_id=self.source,
                turn_index=turn_index,
                perception=self.description,
            ),
            action=ExperienceAction(
                kind=_kind_map.get(self.kind, ExperienceActionKind.attending),
                content=self.description,
            ),
            feeling=ExperienceFeeling(salience=0.3),
        )
