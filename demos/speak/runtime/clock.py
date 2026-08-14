from __future__ import annotations

import time
from datetime import datetime


# 快进时钟默认落在可读日期，便于轻量时间元数据（月-日 时:分）
_DEFAULT_FAKE_START = datetime(2026, 7, 21, 14, 0, 0).timestamp()


class Clock:
    """可替换时钟：真实时间或快进，便于离线演主动开口。"""

    def now(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            time.sleep(seconds)


class FakeClock(Clock):
    def __init__(self, start: float = _DEFAULT_FAKE_START) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        self._now += max(0.0, seconds)

    def advance(self, seconds: float) -> None:
        self._now += max(0.0, seconds)
