from __future__ import annotations

from collections.abc import Callable

from .request import (
    InteractorPortraitPullResult,
    InteractorPortraitRequest,
    PointQueryRequest,
    RecallRequest,
    RecallResult,
    SimilarMemoryPullResult,
)


class InboundMemoryGateway:
    """inbound → memory：recall（同步）与相似记忆点检索（异步 + 有限等待 pull）。"""

    def __init__(
        self,
        recall_fn: Callable[[RecallRequest], RecallResult] | None = None,
        point_query_fn: Callable[[PointQueryRequest], None] | None = None,
        pull_similar_fn: Callable[[str, int, int], SimilarMemoryPullResult] | None = None,
        portrait_query_fn: Callable[[InteractorPortraitRequest], None] | None = None,
        pull_portrait_fn: Callable[[str, int, int], InteractorPortraitPullResult] | None = None,
    ) -> None:
        self._recall_fn = recall_fn
        self._point_query_fn = point_query_fn
        self._pull_similar_fn = pull_similar_fn
        self._portrait_query_fn = portrait_query_fn
        self._pull_portrait_fn = pull_portrait_fn

    def attach_recall(self, recall_fn: Callable[[RecallRequest], RecallResult]) -> None:
        self._recall_fn = recall_fn

    def attach_point_query(self, point_query_fn: Callable[[PointQueryRequest], None]) -> None:
        self._point_query_fn = point_query_fn

    def attach_pull_similar(
        self,
        pull_similar_fn: Callable[[str, int, int], SimilarMemoryPullResult],
    ) -> None:
        self._pull_similar_fn = pull_similar_fn

    def recall(self, request: RecallRequest) -> RecallResult:
        if self._recall_fn is None:
            return RecallResult(ok=False, query=request.query, reason="memory port 未配置")
        return self._recall_fn(request)

    def request_point_query(self, request: PointQueryRequest) -> None:
        if self._point_query_fn is None:
            return
        self._point_query_fn(request)

    def pull_similar_memories(
        self,
        session_id: str,
        turn_index: int,
        *,
        wait_ms: int = 0,
    ) -> SimilarMemoryPullResult:
        if self._pull_similar_fn is None:
            return SimilarMemoryPullResult()
        return self._pull_similar_fn(session_id, turn_index, wait_ms)

    def attach_portrait_query(
        self,
        portrait_query_fn: Callable[[InteractorPortraitRequest], None],
    ) -> None:
        self._portrait_query_fn = portrait_query_fn

    def attach_pull_portrait(
        self,
        pull_portrait_fn: Callable[[str, int, int], InteractorPortraitPullResult],
    ) -> None:
        self._pull_portrait_fn = pull_portrait_fn

    def request_interactor_portrait(self, request: InteractorPortraitRequest) -> None:
        if self._portrait_query_fn is None:
            return
        self._portrait_query_fn(request)

    def pull_interactor_portrait(
        self,
        session_id: str,
        turn_index: int,
        *,
        wait_ms: int = 0,
    ) -> InteractorPortraitPullResult:
        if self._pull_portrait_fn is None:
            return InteractorPortraitPullResult()
        return self._pull_portrait_fn(session_id, turn_index, wait_ms)
