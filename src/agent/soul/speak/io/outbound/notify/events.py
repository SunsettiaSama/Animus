from __future__ import annotations

from typing import Any


def make_notify_event(
    *,
    task: str,
    message: str,
    done: bool = False,
) -> dict[str, Any]:
    """进度条 / toast 类 notify（非主动会话正文）。"""
    return {
        "type": "notify",
        "task": str(task or ""),
        "message": str(message or ""),
        "done": bool(done),
    }


def make_proactive_available_event(
    *,
    session_id: str = "",
    channel_id: str = "",
    proactive_intent_id: str = "",
    delivery_id: str = "",
    source: str = "",
    wait_reply: bool = False,
    online: bool = False,
) -> dict[str, Any]:
    """主动会话可用信号：仅元数据，不含 message 正文。"""
    return {
        "type": "proactive_available",
        "session_id": str(session_id or ""),
        "channel_id": str(channel_id or ""),
        "proactive_intent_id": str(proactive_intent_id or ""),
        "delivery_id": str(delivery_id or ""),
        "source": str(source or ""),
        "wait_reply": bool(wait_reply),
        "online": bool(online),
    }
