"""Worker engine — TaoLoop / ConvLoop."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from worker.engine.loop import ConvLoop
    from worker.engine.tao import TaoLoop

__all__ = ["TaoLoop", "ConvLoop"]


def __getattr__(name: str):
    if name == "TaoLoop":
        from worker.engine.tao import TaoLoop as _TaoLoop

        return _TaoLoop
    if name == "ConvLoop":
        from worker.engine.loop import ConvLoop as _ConvLoop

        return _ConvLoop
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
