from __future__ import annotations

from typing import Protocol

from .request import RecallRequest, RecallResult


class MemoryRecallPort(Protocol):
    def recall(self, request: RecallRequest) -> RecallResult: ...
