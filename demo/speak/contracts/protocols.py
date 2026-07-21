from __future__ import annotations

from typing import Protocol


class Clock(Protocol):
    def now(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class TextGenerator(Protocol):
    def generate(self, *, system: str, user: str) -> str: ...


class ShareEventLike(Protocol):
    """舞台 ShareEvent 的结构协议；contracts 不 import stage。"""

    event_id: str
    title: str

    def one_line(self) -> str: ...
