from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .base import BaseAction
    from .executor import ActionExecutor
    from .manager import ToolManager
    from .mcp import BaseMCPTool, MCPRegistry, MCPServerConfig
    from .skill import BaseSkill, SkillMeta, SkillRegistry
    from .tools import ToolMeta, ToolRegistry

__all__ = [
    "BaseAction",
    "ActionExecutor",
    "ToolManager",
    "ToolRegistry",
    "ToolMeta",
    "BaseSkill",
    "SkillRegistry",
    "SkillMeta",
    "BaseMCPTool",
    "MCPServerConfig",
    "MCPRegistry",
]

_lazy: dict[str, str] = {
    "BaseAction": ".base",
    "ActionExecutor": ".executor",
    "ToolManager": ".manager",
    "BaseMCPTool": ".mcp",
    "MCPRegistry": ".mcp",
    "MCPServerConfig": ".mcp",
    "BaseSkill": ".skill",
    "SkillMeta": ".skill",
    "SkillRegistry": ".skill",
    "ToolMeta": ".tools",
    "ToolRegistry": ".tools",
}


def __getattr__(name: str):
    if name in _lazy:
        import importlib
        mod = importlib.import_module(_lazy[name], __name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
