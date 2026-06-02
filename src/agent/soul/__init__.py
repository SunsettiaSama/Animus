"""Soul 域包：顶层符号懒加载，避免 import 子模块时拉起 handlers / 全栈 memory。"""

from __future__ import annotations

import importlib
from typing import Any

_EXPORTS: dict[str, str] = {
    "SoulConfig": "config.soul.config",
    "LifeAction": "agent.soul.handlers",
    "LifeHandler": "agent.soul.handlers",
    "MemoryAction": "agent.soul.handlers",
    "MemoryHandler": "agent.soul.handlers",
    "PersonaAction": "agent.soul.handlers",
    "PersonaHandler": "agent.soul.handlers",
    "SoulChannel": "agent.soul.request",
    "SoulDomain": "agent.soul.request",
    "SoulRequest": "agent.soul.request",
    "SoulService": "agent.soul.service",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    mod = importlib.import_module(target)
    return getattr(mod, name)
