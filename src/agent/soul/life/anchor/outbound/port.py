from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


@dataclass
class ProactiveOutboundIntent:
    """Agent 主动向用户发起会话的意图（出站链路，待投递）。"""

    message: str
    reason: str = ""
    session_id: str = "tao"
    salience: float = 0.4
    id: str = field(default_factory=_uid)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "message": self.message,
            "reason": self.reason,
            "session_id": self.session_id,
            "salience": self.salience,
            "created_at": self.created_at,
        }


class ProactiveOutboundPort(Protocol):
    """出站链路接口：Agent → 用户主动会话。

    生命周期
    --------
    1. ``submit(intent)`` — 提交主动会话意图
    2. ``list_pending()`` — 运行时拉取待投递（ChannelRouter / TaoLoop 后续接线）
    3. ``acknowledge(intent_id)`` — 投递完成或用户已回应
    """

    def submit(self, intent: ProactiveOutboundIntent) -> str: ...

    def list_pending(self) -> list[ProactiveOutboundIntent]: ...

    def acknowledge(self, intent_id: str) -> None: ...


class InMemoryProactiveOutbound:
    """占位实现：内存队列，暂不实际投递。"""

    def __init__(self) -> None:
        self._pending: list[ProactiveOutboundIntent] = []

    def submit(self, intent: ProactiveOutboundIntent) -> str:
        self._pending.append(intent)
        return intent.id

    def list_pending(self) -> list[ProactiveOutboundIntent]:
        return list(self._pending)

    def acknowledge(self, intent_id: str) -> None:
        self._pending = [i for i in self._pending if i.id != intent_id]
