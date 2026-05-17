from __future__ import annotations

from typing import Any, ClassVar
from urllib.parse import quote

from pydantic import BaseModel, Field

from ...action.skill.base import BaseSkill


class ArxivFrontierReportArgs(BaseModel):
    query: str = Field(
        ...,
        min_length=1,
        description=(
            "arXiv 检索式。可为关键词（将按 all: 字段检索），"
            "或标准语法如 cat:cs.CL、au:smith、ti:transformer"
        ),
    )
    max_results: int = Field(20, ge=5, le=50, description="API 返回条目上限")
    max_chars: int = Field(
        18000,
        ge=4000,
        le=20000,
        description="抓取 API 响应的最大字符数",
    )


def _arxiv_api_url(search_query: str, max_results: int) -> str:
    q = search_query.strip()
    if ":" not in q:
        q = f"all:{q}"
    encoded = quote(q, safe=":")
    return (
        "https://export.arxiv.org/api/query?"
        f"search_query={encoded}&sortBy=submittedDate&sortOrder=descending"
        f"&max_results={max_results}"
    )


class ArxivFrontierReportSkill(BaseSkill):
    """
    调用 arXiv API 拉取最新提交/更新论文条目，经 LLM 汇总为前沿简报。
    """

    name: str = "arxiv_frontier_report"
    description: str = (
        "基于 arXiv API 检索最新论文并生成前沿简报。"
        "参数：query（关键词或 arXiv 检索式），max_results（条数 5-50，默认 20），"
        "max_chars（响应截断上限，默认 18000）"
    )
    skill_type: str = "chain"
    version: str = "1.0.0"
    args_model: ClassVar[type[BaseModel]] = ArxivFrontierReportArgs

    llm: Any = None
    web_fetch: Any = None

    def execute(
        self,
        query: str,
        max_results: int = 20,
        max_chars: int = 18000,
        **kwargs,
    ) -> str:
        if self.web_fetch is None:
            return "ArxivFrontierReportSkill 需要注入 web_fetch 工具。"
        if self.llm is None:
            return "ArxivFrontierReportSkill 需要注入 LLM 实例。"

        url = _arxiv_api_url(query, max_results)
        raw = self.web_fetch.execute(url=url, max_chars=max_chars)

        synthesis_prompt = (
            "你是科研简报编辑。以下为 arXiv Atom API 返回的 XML/文本，可能含大量元数据。"
            "请输出 Markdown 报告：\n"
            "1. 检索意图简述（基于用户 query）\n"
            "2. 最新论文列表：每项含标题、作者（可缩写）、摘要一句话、arXiv ID 或链接线索（从条目中提取）\n"
            "3. 主题簇：将论文按子主题分组 2-4 组，每组一两句话趋势判断\n"
            "4. 局限：API 截断或字段缺失时在文末注明\n\n"
            f"检索式编码前：{query}\n"
            f"API：{url}\n\n"
            f"原始响应：\n{raw}"
        )

        report = self.llm.generate(synthesis_prompt)
        return "\n".join([
            "## arXiv 前沿论文简报",
            "",
            report,
            "",
            "### 数据",
            f"- API：`{url}`",
        ])
