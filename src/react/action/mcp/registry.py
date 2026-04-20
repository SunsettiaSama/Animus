from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from langchain_core.tools import BaseTool

from react.action.mcp.base import MCPServerConfig


@dataclass
class MCPToolInfo:
    """MCPRegistry 维护的工具元信息（在 load_tools 之后填充）。"""

    name: str
    description: str
    server_name: str
    input_schema: dict = field(default_factory=dict)


class MCPRegistry:
    """
    MCP 服务器注册表。

    职责
    ----
    - 管理多个 MCP 服务器的连接配置（MCPServerConfig）。
    - 按需加载服务器上暴露的工具，返回 LangChain BaseTool 实例。
    - 维护已加载工具的元信息，供 ToolManager.search() 使用。

    工具流向
    --------
    MCPRegistry.load_tools()
        → list[BaseTool]  （来自 langchain_mcp_adapters）
        → ActionExecutor.register_instance(tool)  （BaseTool 实例）

    依赖
    ----
    需要安装 langchain_mcp_adapters：
        pip install langchain-mcp-adapters

    示例
    ----
    ```python
    reg = MCPRegistry()
    reg.add_server(MCPServerConfig(
        name="filesystem",
        transport="stdio",
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
    ))
    tools = reg.load_tools("filesystem")  # 返回 list[BaseTool]
    ```
    """

    def __init__(self) -> None:
        self._servers: dict[str, MCPServerConfig] = {}
        self._tool_info: dict[str, MCPToolInfo] = {}   # tool_name → MCPToolInfo

    # --- 服务器管理 ---

    def add_server(self, config: MCPServerConfig) -> None:
        self._servers[config.name] = config

    def remove_server(self, name: str) -> None:
        self._servers.pop(name, None)

    def server_names(self) -> list[str]:
        return list(self._servers.keys())

    def get_server(self, name: str) -> MCPServerConfig | None:
        return self._servers.get(name)

    # --- 工具加载 ---

    def load_tools(self, server_name: str) -> list[BaseTool]:
        """
        同步加载指定 MCP 服务器的工具列表。

        内部通过 asyncio.run() 调用异步客户端。
        返回的 BaseTool 实例可直接传入 ActionExecutor.register_instance()。
        """
        if server_name not in self._servers:
            raise ValueError(f"未知 MCP 服务器: {server_name!r}")
        cfg = self._servers[server_name]
        tools = asyncio.run(self._async_load(cfg))
        self._cache_tool_info(tools, server_name)
        return tools

    def load_all(self) -> list[BaseTool]:
        """加载所有已注册服务器的工具。"""
        tools: list[BaseTool] = []
        for name in self._servers:
            tools.extend(self.load_tools(name))
        return tools

    async def async_load_tools(self, server_name: str) -> list[BaseTool]:
        """异步版本，适合在 async 上下文中调用。"""
        if server_name not in self._servers:
            raise ValueError(f"未知 MCP 服务器: {server_name!r}")
        cfg = self._servers[server_name]
        tools = await self._async_load(cfg)
        self._cache_tool_info(tools, server_name)
        return tools

    async def async_load_all(self) -> list[BaseTool]:
        """异步加载所有服务器的工具。"""
        tools: list[BaseTool] = []
        for name in self._servers:
            tools.extend(await self.async_load_tools(name))
        return tools

    # --- 内部实现 ---

    async def _async_load(self, cfg: MCPServerConfig) -> list[BaseTool]:
        from langchain_mcp_adapters.client import MultiServerMCPClient  # lazy import

        client_dict = {cfg.name: cfg.to_client_dict()}
        async with MultiServerMCPClient(client_dict) as client:
            return client.get_tools()

    def _cache_tool_info(self, tools: list[BaseTool], server_name: str) -> None:
        for tool in tools:
            schema = getattr(tool, "args_schema", None)
            self._tool_info[tool.name] = MCPToolInfo(
                name=tool.name,
                description=tool.description or "",
                server_name=server_name,
                input_schema=schema.model_json_schema() if schema else {},
            )

    # --- 元信息查询（供 ToolManager.search() 使用） ---

    def loaded_tool_info(self) -> list[MCPToolInfo]:
        """返回已加载工具的元信息。"""
        return list(self._tool_info.values())

    def search(
        self,
        query: str,
        top_k: int = 5,
        exclude: list[str] | None = None,
    ) -> list[MCPToolInfo]:
        """在已加载的 MCP 工具中按关键词搜索。"""
        exclude_set = set(exclude or [])
        words = query.lower().split()
        scored: list[tuple[int, MCPToolInfo]] = []
        for info in self._tool_info.values():
            if info.name in exclude_set:
                continue
            corpus = f"{info.name} {info.description} {info.server_name} mcp".lower()
            score = sum(1 for w in words if w in corpus)
            if score > 0:
                scored.append((score, info))
        scored.sort(key=lambda x: -x[0])
        return [m for _, m in scored[:top_k]]

    def __len__(self) -> int:
        return len(self._servers)

    def __contains__(self, name: str) -> bool:
        return name in self._servers
