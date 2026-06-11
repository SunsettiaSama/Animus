from __future__ import annotations

from ..core.base import BlockContext
from ..core.types import BlockId, BlockSnapshot


def memory_snapshot(ctx: BlockContext) -> BlockSnapshot:
    return BlockSnapshot(block="memory", summary="", extra={"buffer": "warm"})
