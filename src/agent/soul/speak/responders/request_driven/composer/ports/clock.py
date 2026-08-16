from __future__ import annotations

import time
from typing import Protocol


class ClockPort(Protocol):
    def now(self) -> float: ...


class MonotonicClock:
    def now(self) -> float:
        return time.monotonic()
