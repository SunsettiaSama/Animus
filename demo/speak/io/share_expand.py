from __future__ import annotations

from typing import Protocol

from ..stage.models import ShareEvent


class ShareExpandPort(Protocol):
    """
    分享条目展开检索口（预留给 soul.memory）。

    rhythm 在 share 之后的下一次 poll 可带 tag=expand，经此口取见闻材料，
    避免回复侧干巴巴编造。
    """

    def retrieve(self, event: ShareEvent) -> str: ...


class NullShareExpand:
    """占位：尚未接线记忆模块时返回空串。"""

    def retrieve(self, event: ShareEvent) -> str:
        del event
        # TODO(soul.memory): 按 ShareEvent 检索相关见闻 / 记忆片段
        return ""
