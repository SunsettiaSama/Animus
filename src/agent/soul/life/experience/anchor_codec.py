from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .unit import ExperienceUnit

_CTX_PREFIX = "__actx:"


class InteractionDirection(str, Enum):
    """锚点层交互方向：现实 ↔ 用户的双向通道。"""

    inbound = "inbound"
    outbound = "outbound"


@dataclass(frozen=True)
class AnchorUnitContext:
    """锚点层 → 编排器：用户交互 unit 的上下文（编码于 prior_thought）。"""

    direction: InteractionDirection
    session_id: str = "tao"
    proactive_intent_id: str = ""

    def to_dict(self) -> dict:
        return {
            "direction": self.direction.value,
            "session_id": self.session_id,
            "proactive_intent_id": self.proactive_intent_id,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AnchorUnitContext:
        return cls(
            direction=InteractionDirection(d.get("direction", InteractionDirection.inbound.value)),
            session_id=str(d.get("session_id", "tao")),
            proactive_intent_id=str(d.get("proactive_intent_id", "")),
        )


def stamp_anchor_context(unit: ExperienceUnit, ctx: AnchorUnitContext) -> None:
    unit.situation.prior_thought = _CTX_PREFIX + json.dumps(
        ctx.to_dict(), ensure_ascii=False
    )


def read_anchor_context(unit: ExperienceUnit) -> AnchorUnitContext | None:
    raw = (unit.situation.prior_thought or "").strip()
    if not raw.startswith(_CTX_PREFIX):
        return None
    payload = json.loads(raw[len(_CTX_PREFIX):])
    return AnchorUnitContext.from_dict(payload)
