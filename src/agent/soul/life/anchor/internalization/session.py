from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agent.soul.life.experience.anchor_codec import InteractionDirection

from .turn import InteractionTurn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


@dataclass
class InteractionSession:
    """一次现实相遇（会话级），闭合后才内化为主体验单元。"""

    session_id: str
    direction: InteractionDirection
    id: str = field(default_factory=_uid)
    opened_at: str = field(default_factory=_now_iso)
    last_at: str = field(default_factory=_now_iso)
    proactive_intent_id: str = ""
    outbound_message: str = ""
    outbound_reason: str = ""
    turns: list[InteractionTurn] = field(default_factory=list)

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    def touch(self) -> None:
        self.last_at = _now_iso()
