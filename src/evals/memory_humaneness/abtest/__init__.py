"""拟人度 AB 管线：软约束标注 A/B（与检索评测管线职能分离）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .design import ABDesign, build_ab_designs, load_designs, validate_ab_designs
    from .runner import ABRecord, ABRunner

_LAZY: dict[str, tuple[str, str]] = {
    "ABDesign": ("evals.memory_humaneness.abtest.design", "ABDesign"),
    "build_ab_designs": ("evals.memory_humaneness.abtest.design", "build_ab_designs"),
    "load_designs": ("evals.memory_humaneness.abtest.design", "load_designs"),
    "validate_ab_designs": ("evals.memory_humaneness.abtest.design", "validate_ab_designs"),
    "ABRecord": ("evals.memory_humaneness.abtest.runner", "ABRecord"),
    "ABRunner": ("evals.memory_humaneness.abtest.runner", "ABRunner"),
}

__all__ = list(_LAZY)


def __getattr__(name: str):
    entry = _LAZY.get(name)
    if entry is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module_name, attr = entry
    value = getattr(importlib.import_module(module_name), attr)
    globals()[name] = value
    return value
