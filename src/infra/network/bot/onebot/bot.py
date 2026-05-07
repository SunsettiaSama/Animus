from __future__ import annotations

from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from .transport.base import BaseTransport
    from .event import MessageEvent
    from .message import Message


def _parse_msg_id(value: object) -> "Union[int, str]":
    """Return message_id as int when possible, otherwise keep it as a string.

    QQ Official API returns string tokens (e.g. ``ROBOT1.0_…``); standard
    OneBot 11 returns numeric IDs.
    """
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (ValueError, TypeError):
        return str(value)


class BotAPI:
    """Typed outbound API for an OneBot 11 bot.

    Wraps transport.call_action() with friendly named methods so callers
    never need to know raw action names.
    """

    def __init__(self, transport: "BaseTransport") -> None:
        self._transport = transport

    # ── High-level helpers ────────────────────────────────────────────────────

    async def send_reply(
        self,
        event: "MessageEvent",
        msg: "Union[str, Message]",
    ) -> "Union[int, str]":
        text = str(msg)
        if event.message_type == "group" and event.group_id is not None:
            return await self.send_group_msg(event.group_id, text)
        return await self.send_private_msg(event.user_id, text)

    # ── Primitives ────────────────────────────────────────────────────────────

    async def send_private_msg(
        self,
        user_id: int,
        msg: "Union[str, Message]",
    ) -> "Union[int, str]":
        res = await self._transport.call_action(
            "send_private_msg",
            {"user_id": user_id, "message": str(msg)},
        )
        return _parse_msg_id((res.get("data") or {}).get("message_id", 0))

    async def send_group_msg(
        self,
        group_id: int,
        msg: "Union[str, Message]",
    ) -> "Union[int, str]":
        res = await self._transport.call_action(
            "send_group_msg",
            {"group_id": group_id, "message": str(msg)},
        )
        return _parse_msg_id((res.get("data") or {}).get("message_id", 0))

    async def call_action(self, action: str, params: dict) -> dict:
        return await self._transport.call_action(action, params)
