from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from worker.tools.base import BaseAction
from worker.tools.builtin.commands.catalog import search_commands


class CommandLookupArgs(BaseModel):
    query: str = Field(..., min_length=1, description="要查找的命令意图，如「显示当前目录」或「list files」")
    family: str = Field("", description="可选，限定 shell 族：powershell / bash / winnt")
    group: str = Field("", description="可选，限定分组：filesystem / process / env / network 等")
    top_k: int = Field(5, ge=1, le=20, description="返回条目数，默认 5")


class CommandLookupAction(BaseAction):
    name: str = "command_lookup"
    description: str = (
        "在 powershell / bash / winnt 命令目录中按意图检索基础命令。"
        "返回 template 与 run_tool，供后续调用对应 shell 执行器。"
        "参数：query（必填）；family（可选）；group（可选）；top_k（可选，默认 5）"
    )
    args_model: ClassVar[type[BaseModel]] = CommandLookupArgs

    def execute(
        self,
        query: str,
        family: str = "",
        group: str = "",
        top_k: int = 5,
        **kwargs,
    ) -> str:
        hits = search_commands(
            query.strip(),
            family=(family or "").strip(),
            group=(group or "").strip(),
            top_k=int(top_k),
        )
        if not hits:
            return (
                f"未在命令目录中找到与「{query}」匹配的条目。\n"
                "可调整 family/group 或换用更短的关键词后重试。"
            )

        lines = [
            f"找到 {len(hits)} 条相关命令（均未写入系统工具列表，请用 run_tool 执行 template）：",
            "",
        ]
        for entry in hits:
            lines.append(entry.render())
        return "\n".join(lines).strip()
