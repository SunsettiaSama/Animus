from __future__ import annotations

import re
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from react.action.skill.base import BaseSkill


class WebResearchArgs(BaseModel):
    topic: str = Field(..., min_length=1, description="调研主题，如「量子计算最新进展」")
    max_pages: int = Field(3, ge=1, le=6, description="最多抓取页面数，默认 3")
    max_results: int = Field(5, ge=1, le=8, description="搜索返回结果数，默认 5")


class WebResearchSkill(BaseSkill):
    """
    深度网络调研技能：
    Phase 1 — web_search 搜索 N 条链接
    Phase 2 — web_fetch 逐个抓取正文（最多 max_pages 页）
    Phase 3 — LLM 综合所有内容，生成结构化研究报告
    """

    name: str = "web_research"
    description: str = (
        "对指定主题进行深度网络调研：自动搜索相关链接、抓取页面内容、LLM 综合生成研究报告。"
        "参数：topic（调研主题），max_pages（最多抓取页面数，默认 3），max_results（搜索结果数，默认 5）"
    )
    skill_type: str = "chain"
    version: str = "1.0.0"
    args_model: ClassVar[type[BaseModel]] = WebResearchArgs

    llm: Any = None
    web_search: Any = None
    web_fetch: Any = None

    _RE_URL = re.compile(r"URL:\s*(https?://\S+)")

    def _extract_urls(self, search_output: str) -> list[str]:
        return self._RE_URL.findall(search_output)

    def execute(self, topic: str, max_pages: int = 3, max_results: int = 5, **kwargs) -> str:
        log: list[str] = []

        if self.web_search is None:
            return "WebResearchSkill 需要注入 web_search 工具。"
        if self.llm is None:
            return "WebResearchSkill 需要注入 LLM 实例。"

        search_output = self.web_search.execute(query=topic, max_results=max_results)
        urls = self._extract_urls(search_output)
        log.append(f"搜索「{topic}」得到 {len(urls)} 条链接")

        pages: list[str] = []
        for url in urls[:max_pages]:
            if self.web_fetch is not None:
                content = self.web_fetch.execute(url=url, max_chars=4000)
                pages.append(f"[来源：{url}]\n{content}")
                log.append(f"已抓取：{url}")

        if not pages:
            pages_text = "（未能抓取任何页面，仅基于搜索摘要）\n\n" + search_output
        else:
            pages_text = "\n\n---\n\n".join(pages)

        synthesis_prompt = (
            f"你是一位专业的研究分析师。请基于以下网络资料，对主题「{topic}」撰写一份结构化研究报告。\n\n"
            "报告应包含：\n"
            "1. 核心发现摘要（3-5 条要点）\n"
            "2. 详细分析（按逻辑分段）\n"
            "3. 主要来源和可信度评估\n"
            "4. 结论与建议\n\n"
            f"资料内容：\n{pages_text[:12000]}"
        )

        report = self.llm.generate(synthesis_prompt)

        result_parts = [
            f"## 调研报告：{topic}",
            f"\n### 数据来源",
            f"- 搜索结果：{len(urls)} 条",
            f"- 已抓取页面：{len(pages)} 个",
            f"\n### 报告内容",
            report,
            f"\n### 执行日志",
            "\n".join(f"  {line}" for line in log),
        ]
        return "\n".join(result_parts)
