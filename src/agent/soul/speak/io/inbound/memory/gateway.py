from __future__ import annotations

from collections.abc import Callable

from .request import (
    InteractorPortraitPullResult,
    InteractorPortraitRequest,
    KeywordQueryRequest,
    PointQueryRequest,
    RecallRequest,
    RecallResult,
    SimilarMemoryPullResult,
)

PullSimilarFn = Callable[..., SimilarMemoryPullResult]


class InboundMemoryGateway:
    """inbound → memory：recall、涌现检索、关键字检索与 compose pull。"""

    def __init__(
        self,
        recall_fn: Callable[[RecallRequest], RecallResult] | None = None,
        point_query_fn: Callable[[PointQueryRequest], None] | None = None,
        keyword_query_fn: Callable[[KeywordQueryRequest], None] | None = None,
        pull_similar_fn: PullSimilarFn | None = None,
        portrait_query_fn: Callable[[InteractorPortraitRequest], None] | None = None,
        pull_portrait_fn: Callable[[str, int, int], InteractorPortraitPullResult] | None = None,
    ) -> None:
        self._recall_fn = recall_fn
        self._point_query_fn = point_query_fn
        self._keyword_query_fn = keyword_query_fn
        self._pull_similar_fn = pull_similar_fn
        self._portrait_query_fn = portrait_query_fn
        self._pull_portrait_fn = pull_portrait_fn

    def attach_recall(self, recall_fn: Callable[[RecallRequest], RecallResult]) -> None:
        self._recall_fn = recall_fn

    def attach_point_query(self, point_query_fn: Callable[[PointQueryRequest], None]) -> None:
        self._point_query_fn = point_query_fn

    def attach_keyword_query(
        self,
        keyword_query_fn: Callable[[KeywordQueryRequest], None],
    ) -> None:
        self._keyword_query_fn = keyword_query_fn

    def attach_pull_similar(self, pull_similar_fn: PullSimilarFn) -> None:
        self._pull_similar_fn = pull_similar_fn

    def recall(self, request: RecallRequest) -> RecallResult:
        if self._recall_fn is None:
            return RecallResult(ok=False, query=request.query, reason="memory port 未配置")
        return self._recall_fn(request)

    def request_point_query(self, request: PointQueryRequest) -> None:
        if self._point_query_fn is None:
            return
        self._point_query_fn(request)

    def request_keyword_query(self, request: KeywordQueryRequest) -> None:
        if self._keyword_query_fn is None:
            return
        self._keyword_query_fn(request)

    def pull_similar_memories(
        self,
        session_id: str,
        turn_index: int,
        *,
        keyword_wait_ms: int = 200,
        budget: int = 5,
        merge_ratio: float | None = None,
        user_text: str = "",
    ) -> SimilarMemoryPullResult:
        if self._pull_similar_fn is None:
            return SimilarMemoryPullResult()
        return self._pull_similar_fn(
            session_id,
            turn_index,
            keyword_wait_ms=keyword_wait_ms,
            budget=budget,
            merge_ratio=merge_ratio,
            user_text=user_text,
        )

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
