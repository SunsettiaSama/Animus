from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class PresenceStateBlockKind(str, Enum):
    experience = "experience"
    rumination = "rumination"


@dataclass
class PresenceStateBlock:
    """外部注入的体验块 / 记忆反刍块 → 本地状态转移与分享队列。"""

    kind: PresenceStateBlockKind
    session_id: str = "tao"
    narratives: dict[str, str] = field(default_factory=dict)
    meta: dict[str, str] = field(default_factory=dict)

    @classmethod
    def experience(
        cls,
        *,
        session_id: str = "tao",
        narratives: dict[str, str] | None = None,
        meta: dict[str, str] | None = None,
    ) -> PresenceStateBlock:
        return cls(
            kind=PresenceStateBlockKind.experience,
            session_id=session_id,
            narratives=dict(narratives or {}),
            meta=dict(meta or {}),
        )

    @classmethod
    def rumination(
        cls,
        *,
        session_id: str = "tao",
        narratives: dict[str, str] | None = None,
        meta: dict[str, str] | None = None,
    ) -> PresenceStateBlock:
        return cls(
            kind=PresenceStateBlockKind.rumination,
            session_id=session_id,
            narratives=dict(narratives or {}),
            meta=dict(meta or {}),
        )
