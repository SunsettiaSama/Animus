from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from langchain_core.tools import BaseTool

if TYPE_CHECKING:
    from ...action.base import BaseAction


@dataclass
class ToolMeta:
    name: str
    description: str
    category: str
    action_cls: type[BaseAction]
    tags: list[str] = field(default_factory=list)


@dataclass
class ToolPackage:
    """命名工具包：一组有语义边界的工具名称集合。

    用途
    ----
    · 主 agent（Planner）与子 agent（Executor / SubAgent）使用不同的包，
      实现工具套组的显式隔离。
    · SubAgentProfile.tool_package 引用包名即可，无需枚举工具名列表。
    · 包可以互相组合：ToolRegistry.resolve_tools() 支持递归展开。
    """

    name: str
    tools: list[str]
    description: str = ""


class ToolRegistry:
    """
    普通工具注册表。

    存放 category 为 math/time/search/conversion/text/random 等的内置工具。
    SkillRegistry 和 MCPRegistry 分别管理各自的工具，通过 ToolManager 汇聚。
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolMeta] = {}
        self._packages: dict[str, ToolPackage] = {}

    def add(
        self,
        action_cls: type[BaseAction],
        category: str = "general",
        tags: list[str] | None = None,
    ) -> type[BaseAction]:
        name = action_cls.model_fields["name"].default
        desc = action_cls.model_fields["description"].default
        self._tools[name] = ToolMeta(
            name=name,
            description=desc,
            category=category,
            action_cls=action_cls,
            tags=tags or [],
        )
        return action_cls

    def get(self, name: str) -> ToolMeta | None:
        return self._tools.get(name)

    def all(self) -> list[ToolMeta]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def by_category(self) -> dict[str, list[ToolMeta]]:
        result: dict[str, list[ToolMeta]] = {}
        for meta in self._tools.values():
            result.setdefault(meta.category, []).append(meta)
        return result

    def search(
        self,
        query: str,
        top_k: int = 5,
        exclude: list[str] | None = None,
    ) -> list[ToolMeta]:
        exclude_set = set(exclude or [])
        words = query.lower().split()
        scored: list[tuple[int, ToolMeta]] = []
        for meta in self._tools.values():
            if meta.name in exclude_set:
                continue
            corpus = " ".join([meta.name, meta.description, meta.category, *meta.tags]).lower()
            score = sum(1 for w in words if w in corpus)
            if score > 0:
                scored.append((score, meta))
        scored.sort(key=lambda x: -x[0])
        return [m for _, m in scored[:top_k]]

    def as_langchain_tools(self, names: list[str] | None = None) -> list[BaseTool]:
        if names is None:
            metas = self._tools.values()
        else:
            metas = [self._tools[n] for n in names if n in self._tools]
        return [meta.action_cls() for meta in metas]

    # ── 工具包管理 ────────────────────────────────────────────────────────────

    def register_package(self, pkg: ToolPackage) -> None:
        """注册一个命名工具包（同名覆盖）。"""
        self._packages[pkg.name] = pkg

    def get_package(self, name: str) -> ToolPackage | None:
        return self._packages.get(name)

    def package_names(self) -> list[str]:
        return list(self._packages.keys())

    def resolve_tools(self, name_or_package: str) -> list[str]:
        """将包名解析为工具名列表。

        · 若参数是已注册的包名 → 返回包内工具列表
        · 若参数是已注册的工具名 → 返回 [name_or_package]
        · 否则返回空列表（调用方可按需报错）
        """
        pkg = self._packages.get(name_or_package)
        if pkg is not None:
            return list(pkg.tools)
        if name_or_package in self._tools:
            return [name_or_package]
        return []

    # ── 基础 ─────────────────────────────────────────────────────────────────

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools
