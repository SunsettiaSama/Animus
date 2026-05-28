from __future__ import annotations

from typing import Protocol

from .request import PointQueryRequest, RecallRequest, RecallResult, SimilarMemoryPullResult


class MemoryRecallPort(Protocol):
    def recall(self, request: RecallRequest) -> RecallResult: ...


class MemoryPointQueryPort(Protocol):
    def request_point_query(self, request: PointQueryRequest) -> None: ...


class MemorySimilarPullPort(Protocol):
    def pull_similar_memories(
        self,
        session_id: str,
        turn_index: int,
    ) -> SimilarMemoryPullResult: ...
