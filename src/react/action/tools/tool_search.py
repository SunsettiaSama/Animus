from __future__ import annotations

from typing import TYPE_CHECKING, Any

from react.action.base import BaseAction

if TYPE_CHECKING:
    from react.action.manager import ToolManager


class ToolSearchAction(BaseAction):
    """
    元工具：在全量工具库中按需搜索。

    当 Agent 发现现有工具不足以解决问题时，可调用此工具查找
    更合适的工具。找到后工具已在 executor 中，可直接调用。
    """

    name: str = "tool_search"
    description: str = (
        "在工具库中搜索合适的工具。当现有工具无法满足需求时调用。"
        "参数：query（描述你需要的功能，如 '随机数' 或 'base64编码'）；"
        "top_k（可选，返回结果数，默认 3）"
    )

    manager: Any = None  # ToolManager，arbitrary_types_allowed 已由 BaseTool 开启

    def execute(self, query: str = "", top_k: int = 3, **kwargs) -> str:
        if not query:
            raise ValueError("缺少参数 query")

        results = self.manager.search(query.strip(), int(top_k))

        if not results:
            return (
                f"未在工具库中找到与「{query}」相关的工具。\n"
                "可用类别：数学(math)、时间(time)、搜索(search)、"
                "单位换算(conversion)、文本(text)、随机(random)"
            )

        lines = [f"找到 {len(results)} 个相关工具（均已可直接调用）：\n"]
        for meta in results:
            lines.append(f"工具名：{meta.name}")
            lines.append(f"  类别：{meta.category}")
            lines.append(f"  功能：{meta.description}")
            lines.append("")

        return "\n".join(lines).strip()
