from __future__ import annotations

import asyncio
from typing import Any, Callable, Protocol


class SpeakNotifyPort(Protocol):
    """Notify 出站口：推送元数据唤醒事件，不承载正文流。"""

    def publish(self, item: dict[str, Any]) -> None: ...


class SpeakNotifySubscriberPort(Protocol):
    """按 channel 订阅 notify 出站；由外部 state / SSE 接线实现。"""

    def attach(
        self,
        channel_id: str,
        queue: asyncio.Queue,
    ) -> Callable[[], None]: ...
