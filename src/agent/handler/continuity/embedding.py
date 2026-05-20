from __future__ import annotations

import math
from collections.abc import Callable


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class CallableContinuityEmbedHandler:
    """将 ``embed(text) -> vector`` 适配为 :class:`ContinuityEmbedHandler`。"""

    def __init__(self, fn: Callable[[str], list[float]]) -> None:
        self._fn = fn

    def embed(self, text: str) -> list[float]:
        return self._fn(text)
