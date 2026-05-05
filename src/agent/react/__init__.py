from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tao import TaoLoop
    from .loop import ConvLoop

__all__ = ["TaoLoop", "ConvLoop"]

_lazy: dict[str, str] = {
    "TaoLoop": ".tao",
    "ConvLoop": ".loop",
}


def __getattr__(name: str):
    if name in _lazy:
        import importlib
        mod = importlib.import_module(_lazy[name], __name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
