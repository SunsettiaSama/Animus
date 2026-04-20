from __future__ import annotations

import json

from langchain_core.tools import BaseTool

from .base import BaseAction


class ActionExecutor:
    """
    工具执行器。

    支持三种注册方式：
    - register(cls)               → 类注册（BaseAction 子类），每次调用时实例化
    - register_instance(action)   → 实例注册（BaseAction 实例，持有外部依赖）
    - register_lc_tool(tool)      → LangChain BaseTool 实例注册（MCP 工具等）

    run() 调用优先级：
      instances > lc_tools > registry
    """

    def __init__(self) -> None:
        self._registry: dict[str, type[BaseAction]] = {}
        self._instances: dict[str, BaseAction] = {}
        self._lc_tools: dict[str, BaseTool] = {}      # 纯 LangChain BaseTool（如 MCP）

    # --- 注册 ---

    def register(self, action_cls: type[BaseAction]) -> type[BaseAction]:
        name = action_cls.model_fields["name"].default
        self._registry[name] = action_cls
        return action_cls

    def register_instance(self, action: BaseAction) -> BaseAction:
        """注册预构建 BaseAction 实例（如需注入 manager 依赖的元工具）。"""
        self._instances[action.name] = action
        return action

    def register_lc_tool(self, tool: BaseTool) -> BaseTool:
        """注册原生 LangChain BaseTool 实例（来自 MCP、LangChain Hub 等）。"""
        self._lc_tools[tool.name] = tool
        return tool

    # --- 执行 ---

    def run(self, json_input: str) -> str:
        payload: dict = json.loads(json_input)
        action_name: str = payload["action"]
        args: dict = payload.get("args", {})

        if action_name in self._instances:
            return self._instances[action_name].execute(**args)

        if action_name in self._lc_tools:
            result = self._lc_tools[action_name].invoke(args)
            return str(result)

        if action_name not in self._registry:
            raise ValueError(
                f"未知工具: {action_name!r}。"
                f"可用工具: {self.available_actions}"
            )

        return self._registry[action_name]().execute(**args)

    # --- LangChain 接口 ---

    def as_langchain_tools(self) -> list[BaseTool]:
        """返回所有工具的 BaseTool 实例列表，可直接传入 LangChain Agent。"""
        tools: list[BaseTool] = [cls() for cls in self._registry.values()]
        tools.extend(self._instances.values())
        tools.extend(self._lc_tools.values())
        return tools

    # --- 查询 ---

    @property
    def available_actions(self) -> list[str]:
        return sorted(set(self._registry) | set(self._instances) | set(self._lc_tools))
