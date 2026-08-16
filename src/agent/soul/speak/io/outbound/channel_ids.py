from __future__ import annotations


def normalize_channel_id(channel_id: str = "", session_id: str = "") -> str:
    """裸 channel：去掉 live: 前缀，供 SSE / Hub 按渠道路由。"""
    cid = str(channel_id or "").strip()
    if cid.startswith("live:"):
        return cid[5:].strip()
    sid = str(session_id or "").strip()
    if not cid and sid.startswith("live:"):
        return sid[5:].strip()
    return cid or sid


def live_session_id(channel_id: str = "", session_id: str = "") -> str:
    """WebUI Speak 生命线 session：live:{channel}。"""
    cid = normalize_channel_id(channel_id, session_id)
    if cid:
        return f"live:{cid}"
    sid = str(session_id or "").strip()
    if sid.startswith("live:"):
        return sid
    return sid
