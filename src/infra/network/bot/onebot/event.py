from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


@dataclass
class Event:
    time: int
    self_id: int
    post_type: str


@dataclass
class Sender:
    user_id: int
    nickname: str
    card: str = ""
    role: str = ""   # owner | admin | member (group only)


@dataclass
class MessageEvent(Event):
    message_type: str = ""     # private | group
    sub_type: str = ""
    message_id: int = 0
    user_id: int = 0
    message: list[dict] = field(default_factory=list)   # raw OneBot 11 segments
    raw_message: str = ""
    font: int = 0
    sender: Sender = field(default_factory=lambda: Sender(0, ""))
    group_id: int | None = None

    # Human-readable access-control key:
    #   forward_ws  → str(QQ number), e.g. "1219584142"
    #   qq_official → raw openid string from QQ Open Platform
    # Used exclusively for whitelist matching; user_id/group_id remain numeric.
    user_key: str = ""
    group_key: str = ""

    @property
    def session_id(self) -> str:
        if self.message_type == "group":
            return f"group_{self.group_id}"
        return f"private_{self.user_id}"

    @property
    def plain_text(self) -> str:
        parts: list[str] = []
        for seg in self.message:
            if seg.get("type") == "text":
                parts.append(seg.get("data", {}).get("text", ""))
        return "".join(parts)


@dataclass
class NoticeEvent(Event):
    notice_type: str = ""


@dataclass
class RequestEvent(Event):
    request_type: str = ""
    flag: str = ""


@dataclass
class MetaEvent(Event):
    meta_event_type: str = ""   # lifecycle | heartbeat
    status: dict = field(default_factory=dict)


OBEvent = Union[MessageEvent, NoticeEvent, RequestEvent, MetaEvent]


def parse_event(raw: dict) -> OBEvent:
    post_type = raw.get("post_type", "")
    base = dict(
        time=int(raw.get("time", 0)),
        self_id=int(raw.get("self_id", 0)),
        post_type=post_type,
    )
    if post_type == "message" or post_type == "message_sent":
        sender_raw = raw.get("sender") or {}
        sender = Sender(
            user_id=int(sender_raw.get("user_id", 0)),
            nickname=str(sender_raw.get("nickname", "")),
            card=str(sender_raw.get("card", "")),
            role=str(sender_raw.get("role", "")),
        )
        group_id_raw = raw.get("group_id")
        uid = int(raw.get("user_id", 0))
        gid = int(group_id_raw) if group_id_raw is not None else None
        return MessageEvent(
            **base,
            message_type=str(raw.get("message_type", "")),
            sub_type=str(raw.get("sub_type", "")),
            message_id=int(raw.get("message_id", 0)),
            user_id=uid,
            message=list(raw.get("message") or []),
            raw_message=str(raw.get("raw_message", "")),
            font=int(raw.get("font", 0)),
            sender=sender,
            group_id=gid,
            user_key=str(raw.get("user_key") or uid),
            group_key=str(raw.get("group_key") or gid or ""),
        )
    if post_type == "notice":
        return NoticeEvent(**base, notice_type=str(raw.get("notice_type", "")))
    if post_type == "request":
        return RequestEvent(
            **base,
            request_type=str(raw.get("request_type", "")),
            flag=str(raw.get("flag", "")),
        )
    return MetaEvent(
        **base,
        meta_event_type=str(raw.get("meta_event_type", "")),
        status=dict(raw.get("status") or {}),
    )
