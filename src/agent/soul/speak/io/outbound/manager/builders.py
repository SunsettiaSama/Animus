from __future__ import annotations

from typing import Any

from agent.soul.speak.io.outbound.protocol import OutboundOp, OutboundRequest

from .unit import OutboundMessage


def message_from_request(
    request: OutboundRequest,
    *,
    mode: str = "live",
    channel_id: str = "",
    source: str = "",
) -> OutboundMessage:
    meta = dict(request.meta or {})
    src = str(source or meta.get("source") or "").strip()
    return OutboundMessage(
        session_id=request.session_id.strip(),
        mode="pending" if mode == "pending" else "live",
        channel_id=str(channel_id or "").strip(),
        ops=tuple(request.ops),
        user_text=str(request.user_text or ""),
        created_at=str(meta.get("created_at") or "").strip(),
        source=src,
        text="".join(
            op.text.strip() for op in request.ops if op.kind == "speak" and op.text.strip()
        ),
        meta=meta,
    )


def message_from_speak_text(
    session_id: str,
    text: str,
    *,
    mode: str = "live",
    channel_id: str = "",
    user_text: str = "",
    source: str = "",
    created_at: str = "",
    finish: bool = True,
    meta: dict[str, Any] | None = None,
) -> OutboundMessage:
    body = text.strip()
    ops: list[OutboundOp] = []
    if body:
        ops.append(
            OutboundOp(
                kind="speak",
                text=body,
                meta={"field": "speak", "order": 0, "source": source},
            )
        )
    if finish:
        ops.append(
            OutboundOp(
                kind="finish",
                text="",
                final=True,
                meta={"field": "finish", "order": 1, "source": source},
            )
        )
    return OutboundMessage(
        session_id=session_id.strip(),
        mode="pending" if mode == "pending" else "live",
        channel_id=str(channel_id or "").strip(),
        text=body,
        ops=tuple(ops),
        user_text=user_text,
        created_at=str(created_at or "").strip(),
        source=source,
        meta=dict(meta or {}),
    )


def message_from_pending_payload(payload: dict[str, Any]) -> OutboundMessage:
    raw = dict(payload)
    text = str(raw.get("message") or raw.get("text") or "").strip()
    if not text:
        raise ValueError("pending payload requires message")
    return OutboundMessage(
        session_id=str(raw.get("session_id") or "").strip(),
        mode="pending",
        channel_id=str(raw.get("channel_id") or "").strip(),
        text=text,
        created_at=str(raw.get("created_at") or "").strip(),
        delivery_id=str(raw.get("delivery_id") or "").strip(),
        source=str(raw.get("source") or "").strip(),
        agent_initiated=bool(raw.get("agent_initiated", True)),
        create_window=bool(raw.get("create_window", True)),
        wait_reply=bool(raw.get("wait_reply", False)),
        proactive_intent_id=str(raw.get("proactive_intent_id") or "").strip(),
        banner=str(raw.get("banner") or "").strip(),
        agent_display_name=str(raw.get("agent_display_name") or "").strip(),
        meta={
            key: value
            for key, value in raw.items()
            if key
            not in {
                "session_id",
                "channel_id",
                "message",
                "text",
                "created_at",
                "delivery_id",
                "source",
                "agent_initiated",
                "create_window",
                "wait_reply",
                "proactive_intent_id",
                "banner",
                "agent_display_name",
            }
        },
    )


def request_from_message(message: OutboundMessage) -> OutboundRequest:
    msg = message.stamped()
    meta = dict(msg.meta)
    meta["created_at"] = msg.created_at
    if msg.source:
        meta.setdefault("source", msg.source)
    if msg.delivery_id:
        meta.setdefault("delivery_id", msg.delivery_id)
    ops = msg.ops
    if not ops and msg.text.strip():
        ops = (
            OutboundOp(
                kind="speak",
                text=msg.text.strip(),
                meta={"field": "speak", "order": 0},
            ),
            OutboundOp(
                kind="finish",
                text="",
                final=True,
                meta={"field": "finish", "order": 1},
            ),
        )
    return OutboundRequest(
        session_id=msg.session_id.strip(),
        ops=ops,
        user_text=msg.user_text,
        meta=meta,
    )
