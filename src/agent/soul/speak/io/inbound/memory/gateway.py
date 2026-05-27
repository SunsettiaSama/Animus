from __future__ import annotations

from collections.abc import Callable

from .request import RecallRequest, RecallResult


class InboundMemoryGateway:
    """inbound → memory：为 state:recall 提供检索。"""

    def __init__(
        self,
        recall_fn: Callable[[RecallRequest], RecallResult] | None = None,
    ) -> None:
        self._recall_fn = recall_fn

    def attach_recall(self, recall_fn: Callable[[RecallRequest], RecallResult]) -> None:
        self._recall_fn = recall_fn

    def recall(self, request: RecallRequest) -> RecallResult:
        if self._recall_fn is None:
            return RecallResult(ok=False, query=request.query, reason="memory port 未配置")
        return self._recall_fn(request)
