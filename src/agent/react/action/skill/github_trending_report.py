from __future__ import annotations

from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from ...action.skill.base import BaseSkill


class GitHubTrendingReportArgs(BaseModel):
    since: Literal["daily", "weekly", "monthly"] = Field(
        "daily",
        description="时间窗口：daily / weekly / monthly",
    )
    language: str = Field(
        "",
        description="编程语言 slug（如 python、rust、typescript）；留空表示不限语言",
    )
    max_chars: int = Field(
        16000,
        ge=4000,
        le=20000,
        description="抓取 trending 页的最大字符数",
    )


def _trending_page_url(since: str, language: str) -> str:
    lang = language.strip().lower().replace(" ", "")
    base = "https://github.com/trending"
    if lang:
        base = f"{base}/{lang}"
    return f"{base}?since={since}"


class GitHubTrendingReportSkill(BaseSkill):
    """
    抓取 GitHub Trending 页面，经 LLM 整理为结构化简报。
    """

    name: str = "github_trending_report"
    description: str = (
        "抓取 GitHub Trending（日/周/月），生成前沿仓库趋势报告。"
        "参数：since（daily/weekly/monthly，默认 daily），"
        "language（可选语言 slug，如 python），"
        "max_chars（抓取上限，默认 16000）"
    )
    skill_type: str = "chain"
    version: str = "1.0.0"
    args_model: ClassVar[type[BaseModel]] = GitHubTrendingReportArgs

    llm: Any = None
    web_fetch: Any = None

    def execute(
        self,
        since: str = "daily",
        language: str = "",
        max_chars: int = 16000,
        **kwargs,
    ) -> str:
        if self.web_fetch is None:
            return "GitHubTrendingReportSkill 需要注入 web_fetch 工具。"
        if self.llm is None:
            return "GitHubTrendingReportSkill 需要注入 LLM 实例。"

        url = _trending_page_url(since, language)
        raw = self.web_fetch.execute(url=url, max_chars=max_chars)

        window = {"daily": "今日", "weekly": "本周", "monthly": "本月"}[since]
        lang_note = language.strip() or "全语言"
        synthesis_prompt = (
            f"你是技术趋势编辑。以下为 GitHub Trending 页面（{window}，{lang_note}）的抓取正文，"
            "可能含重复导航或噪音。请输出一份 Markdown 报告，包含：\n"
            "1. 摘要：2-4 句话概括本榜单技术热点\n"
            "2. 榜单仓库：表格或列表，含仓库名、一句话描述、Star 趋势线索（若文中有）\n"
            "3. 值得关注：3-5 条为何值得 follow 的理由或风险提醒\n"
            "4. 数据来源：明确写「来源于 GitHub Trending 页面抓取」并附上 URL\n\n"
            f"页面 URL：{url}\n\n"
            f"抓取内容：\n{raw}"
        )

        report = self.llm.generate(synthesis_prompt)
        return "\n".join([
            f"## GitHub Trending 报告（{window} · {lang_note}）",
            "",
            report,
            "",
            "### 原始抓取概览",
            f"- 页面：{url}",
        ])
