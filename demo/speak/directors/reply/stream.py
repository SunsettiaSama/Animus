from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

StreamKind = Literal["think", "token", "done"]


@dataclass(frozen=True)
class StreamEvent:
    """对外流式事件：前端可按 kind 决定是否渲染 think。"""

    kind: StreamKind
    text: str = ""
    index: int = 0


class StreamSink(Protocol):
    def on_event(self, event: StreamEvent) -> None: ...


class NullSink:
    def on_event(self, event: StreamEvent) -> None:
        del event


class FanoutSink:
    """多个外界 sink 并联。"""

    def __init__(self, *sinks: StreamSink) -> None:
        self._sinks = sinks

    def on_event(self, event: StreamEvent) -> None:
        for sink in self._sinks:
            sink.on_event(event)


class CollectingSink:
    """测试 / 调试：收集事件。"""

    def __init__(self) -> None:
        self.events: list[StreamEvent] = []

    def on_event(self, event: StreamEvent) -> None:
        self.events.append(event)

    @property
    def text(self) -> str:
        return "".join(ev.text for ev in self.events if ev.kind == "token")
