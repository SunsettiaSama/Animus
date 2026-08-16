from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Literal

from agent.soul.speak.io.outbound.protocol import OutboundOp

OutboundDispatchMode = Literal["live", "pending"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True)
class OutboundMessage:
    """出站消息单元：用户即时回复与导演主动开口共用同一形状。"""

    session_id: str
    mode: OutboundDispatchMode = "live"
    channel_id: str = ""
    text: str = ""
    ops: tuple[OutboundOp, ...] = ()
    user_text: str = ""
    created_at: str = ""
    delivery_id: str = ""
    source: str = ""
    agent_initiated: bool = False
    create_window: bool = False
    wait_reply: bool = False
    proactive_intent_id: str = ""
    banner: str = ""
    agent_display_name: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def stamped(self) -> OutboundMessage:
        """固化 speak 时刻；已有 created_at 则不改写。"""
        created = str(self.created_at or "").strip()
        did = str(self.delivery_id or "").strip()
        intent = str(self.proactive_intent_id or "").strip()
        patches: dict[str, Any] = {}
        if not created:
            patches["created_at"] = _now_iso()
        if not did:
            patches["delivery_id"] = intent or _uid()
        if not patches:
            return self
        return replace(self, **patches)

    @property
    def answer_text(self) -> str:
        if self.text.strip():
            return self.text.strip()
        parts = [op.text.strip() for op in self.ops if op.kind == "speak" and op.text.strip()]
        return "".join(parts)

    def to_pending_payload(self) -> dict[str, Any]:
        msg = self.stamped()
        text = msg.answer_text
        if not text:
            raise ValueError("pending OutboundMessage requires speak text")
        if not str(msg.channel_id or "").strip():
            raise ValueError("pending OutboundMessage requires channel_id")
        payload = {
            "session_id": msg.session_id.strip(),
            "channel_id": str(msg.channel_id or "").strip(),
            "message": text,
            "delivery_id": msg.delivery_id,
            "created_at": msg.created_at,
            "agent_initiated": bool(msg.agent_initiated),
            "create_window": bool(msg.create_window),
            "wait_reply": bool(msg.wait_reply),
            "proactive_intent_id": msg.proactive_intent_id or msg.delivery_id,
            "source": msg.source,
            "banner": msg.banner,
            "agent_display_name": msg.agent_display_name,
        }
        for key, value in msg.meta.items():
            if key not in payload and value is not None:
                payload[key] = value
        return payload


@dataclass
class OutboundDispatchResult:
    ok: bool
    mode: OutboundDispatchMode
    message: OutboundMessage
    status: str = ""
    events: list[Any] = field(default_factory=list)
    answer: str = ""
    bus: dict[str, Any] = field(default_factory=dict)
