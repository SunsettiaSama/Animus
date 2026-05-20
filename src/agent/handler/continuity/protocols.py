from __future__ import annotations

from typing import Protocol


class ContinuityEmbedHandler(Protocol):
    """连续性判定用文本嵌入。"""

    def embed(self, text: str) -> list[float]: ...


class ContinuityLlmHandler(Protocol):
    """连续性灰区裁决用短补全。"""

    def complete(self, system: str, user: str) -> str: ...
