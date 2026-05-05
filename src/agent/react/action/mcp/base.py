from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ...action.base import BaseAction


@dataclass
class MCPServerConfig:
    """MCP 服务器连接配置。"""

    name: str
    transport: Literal["stdio", "sse", "streamable_http"] = "stdio"

    # stdio transport
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    # HTTP transport (sse / streamable_http)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def to_client_dict(self) -> dict[str, Any]:
        """转换为 langchain_mcp_adapters.MultiServerMCPClient 所需的字典格式。"""
        if self.transport == "stdio":
            cfg: dict[str, Any] = {
                "command": self.command,
                "args": self.args,
                "transport": "stdio",
            }
            if self.env:
                cfg["env"] = self.env
            return cfg
        cfg = {
            "url": self.url,
            "transport": self.transport,
        }
        if self.headers:
            cfg["headers"] = self.headers
        return cfg


class BaseMCPTool(BaseAction):
    """
    MCP 工具基类。

    表示挂载在某个 MCP 服务器上的单个工具。
    子类或动态创建的实例需要实现 execute()，
    通常通过调用 MCP 客户端来完成。

    字段说明：
    - server_name   : 工具所属的 MCP 服务器名（对应 MCPServerConfig.name）
    - mcp_tool_name : 在 MCP 服务器上注册的工具名（可能与 name 不同）
    - mcp_schema    : 工具的 JSON Schema（从服务器自动获取）
    """

    server_name: str = ""
    mcp_tool_name: str = ""
    mcp_schema: dict = {}

    def execute(self, **kwargs) -> str:
        raise NotImplementedError(
            "BaseMCPTool.execute() 未实现。"
            "请使用 MCPRegistry.load_tools() 加载的具体实例。"
        )
