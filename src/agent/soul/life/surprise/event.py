from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


class SurpriseKind(str, Enum):
    wandering  = "wandering"   # 启动器自然累积触发
    heartbeat  = "heartbeat"   # 心跳漫游信号推送触发（预留）


@dataclass
class SurpriseEvent:
    """一次已落地的意外事件记录。

    意外事件不由 Agent 预约，而由 ``SurpriseLauncher`` 的累积概率触发，
    经 ``SurpriseGenerator`` 填充情节后内化为 ``ExperienceUnit``。

    字段语义
    --------
    - ``narrative``     — 生成的情节文本
    - ``dice_value``    — 触发时的骰点
    - ``dice_tendency`` — 骰点对应的体验基调
    - ``experience_id`` — 关联的 ExperienceUnit.id
    - ``kind``          — 触发来源类型
    """
    narrative:     str
    id:            str          = field(default_factory=_uid)
    ts:            str          = field(default_factory=_now_iso)
    dice_value:    int          = 0
    dice_tendency: str          = ""
    experience_id: str          = ""
    kind:          SurpriseKind = SurpriseKind.wandering

    def to_dict(self) -> dict:
        return {
            "id":            self.id,
            "ts":            self.ts,
            "kind":          self.kind.value,
            "narrative":     self.narrative,
            "dice_value":    self.dice_value,
            "dice_tendency": self.dice_tendency,
            "experience_id": self.experience_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SurpriseEvent:
        return cls(
            id=            d.get("id", _uid()),
            ts=            d.get("ts", _now_iso()),
            kind=          SurpriseKind(d.get("kind", "wandering")),
            narrative=     d.get("narrative", ""),
            dice_value=    d.get("dice_value", 0),
            dice_tendency= d.get("dice_tendency", ""),
            experience_id= d.get("experience_id", ""),
        )
