from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from react.action.skill.base import BaseSkill


class DocumentSummaryArgs(BaseModel):
    path: str = Field(..., min_length=1, description="文件路径（相对于沙箱工作区）")
    mode: Literal["summary", "outline", "compress"] = Field(
        "summary",
        description=(
            "摘要模式：\n"
            "  summary  — 提取要点并写出概述（默认）\n"
            "  outline  — 生成结构化提纲\n"
            "  compress — 将内容压缩为简洁版本，保留关键信息"
        ),
    )
    max_chars: int = Field(20000, ge=1000, le=100000, description="读取文件最大字符数，默认 20000")


_MODE_PROMPTS: dict[str, str] = {
    "summary": (
        "请阅读以下文档内容，提取核心要点并写出一份清晰的摘要。\n"
        "摘要结构：\n"
        "1. 文档概述（1-2 句话）\n"
        "2. 主要内容要点（3-7 条）\n"
        "3. 关键结论或行动项（如有）\n\n"
    ),
    "outline": (
        "请阅读以下文档内容，生成一份层次清晰的结构化提纲。\n"
        "使用 Markdown 标题格式（##、###）组织层次，每节附简短说明。\n\n"
    ),
    "compress": (
        "请将以下文档内容压缩为原文的 20% 左右，保留所有关键信息、数据和结论，"
        "删除冗余描述、例子和修辞。输出应直接可读，无需额外说明。\n\n"
    ),
}


class DocumentSummarySkill(BaseSkill):
    """
    文档读取 + LLM 摘要技能：
    Phase 1 — 通过 file_read 工具读取文件内容
    Phase 2 — LLM 按指定模式生成摘要 / 提纲 / 压缩版本
    """

    name: str = "document_summary"
    description: str = (
        "读取本地文件并用 LLM 生成摘要、提纲或压缩版本。"
        "参数：path（文件路径），"
        "mode（summary/outline/compress，默认 summary），"
        "max_chars（最大读取字符数，默认 20000）"
    )
    skill_type: str = "chain"
    version: str = "1.0.0"
    args_model: ClassVar[type[BaseModel]] = DocumentSummaryArgs

    llm: Any = None
    file_read: Any = None

    def execute(
        self,
        path: str,
        mode: str = "summary",
        max_chars: int = 20000,
        **kwargs,
    ) -> str:
        if self.llm is None:
            return "DocumentSummarySkill 需要注入 LLM 实例。"
        if self.file_read is None:
            return "DocumentSummarySkill 需要注入 file_read 工具实例。"

        raw = self.file_read.execute(path=path, max_chars=max_chars)

        prompt_prefix = _MODE_PROMPTS.get(mode, _MODE_PROMPTS["summary"])
        prompt = f"{prompt_prefix}文档内容：\n{raw}"

        result = self.llm.generate(prompt)

        mode_labels = {"summary": "摘要", "outline": "提纲", "compress": "压缩版本"}
        label = mode_labels.get(mode, mode)
        return f"## 文档{label}：{path}\n\n{result}"
