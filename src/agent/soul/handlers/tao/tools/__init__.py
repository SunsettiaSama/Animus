from __future__ import annotations

from typing import Any

from agent.react.action.base import BaseAction

from .life_chronicle import SoulLifeChronicleAction
from .life_hot import SoulLifeHotAction
from .memory_search import SoulMemorySearchAction
from .persona import SoulPersonaAction

SOUL_TOOL_NAMES: tuple[str, ...] = (
    "soul_persona",
    "soul_memory_search",
    "soul_life_chronicle",
    "soul_life_hot",
)

_REFLECTION_TOOL_NAMES: tuple[str, ...] = SOUL_TOOL_NAMES


def build_soul_tool_instances(soul: Any) -> list[BaseAction]:
    """构建绑定 SoulService 的工具实例。"""
    return [
        SoulPersonaAction(soul=soul),
        SoulMemorySearchAction(soul=soul),
        SoulLifeChronicleAction(soul=soul),
        SoulLifeHotAction(soul=soul),
    ]


def soul_tool_descriptions() -> dict[str, str]:
    return {
        cls.model_fields["name"].default: cls.model_fields["description"].default
        for cls in (
            SoulPersonaAction,
            SoulMemorySearchAction,
            SoulLifeChronicleAction,
            SoulLifeHotAction,
        )
    }


def register_soul_tools(
    executor,
    soul: Any,
    descriptions: dict[str, str],
    *,
    only: set[str] | None = None,
) -> None:
    """向 ActionExecutor 注册 Soul 工具，并合并 prompt 描述。"""
    for action in build_soul_tool_instances(soul):
        if only is not None and action.name not in only:
            continue
        executor.register_instance(action)
        descriptions[action.name] = action.description


def merge_profile_soul_tool_descriptions(
    profile_tools: list[str] | None,
    descriptions: dict[str, str],
) -> None:
    """将 profile.tools 中声明的 Soul 工具描述并入 tool_descriptions。"""
    if not profile_tools:
        return
    meta = soul_tool_descriptions()
    for name in profile_tools:
        if name in meta:
            descriptions[name] = meta[name]
