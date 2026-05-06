from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .event import MessageEvent, MetaEvent, NoticeEvent, RequestEvent
    from .bot import BotAPI


class EventHandler(ABC):
    """Consumer-side interface for OneBot 11 events.

    Concrete handlers (e.g. BotService) override on_message; the other
    handlers default to no-ops so subclasses only implement what they need.
    """

    @abstractmethod
    async def on_message(self, event: "MessageEvent", bot: "BotAPI") -> None: ...

    async def on_notice(self, event: "NoticeEvent", bot: "BotAPI") -> None:
        pass

    async def on_request(self, event: "RequestEvent", bot: "BotAPI") -> None:
        pass

    async def on_meta(self, event: "MetaEvent", bot: "BotAPI") -> None:
        pass
