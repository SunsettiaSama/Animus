from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from ...action.skill.base import BaseSkill
from ...action.skill.source_registry import AuthoritySource, SourceKind, SourceRegistry


class FrontierReportArgs(BaseModel):
    topic: str = Field(..., min_length=1, description="前沿报告主题，如「多模态大语言模型」")
    categories: list[str] = Field(
        default_factory=list,
        description=(
            "可选领域标签辅助选源，如 ['nlp', 'cv']；"
            "留空则由主题关键词自动推断。"
            "可用标签：ai / nlp / cv / ml / robotics / safety / multimodal / rl / retrieval"
        ),
    )
    max_sources: int = Field(8, ge=3, le=20, description="最多激活的信源数量，默认 8")
    max_chars_per_source: int = Field(
        4000, ge=1000, le=12000, description="每个信源最大抓取字符数，默认 4000"
    )
    min_priority: int = Field(
        3, ge=1, le=5, description="信源最低权威等级过滤（1-5），默认 3（过滤掉低质量信源）"
    )
    arxiv_max_results: int = Field(
        12, ge=5, le=30, description="arXiv API 每次返回的论文条数上限，默认 12"
    )


_KIND_HEADING: dict[SourceKind, str] = {
    "arxiv":      "### arXiv 最新论文",
    "blog":       "### 顶级研究机构最新成果",
    "conference": "### 顶会最新动态",
    "aggregator": "### 权威资讯聚合",
}

_KIND_PROMPT: dict[SourceKind, str] = {
    "arxiv": (
        "以下是来自 arXiv 的论文检索结果（Atom XML 格式），主题「{topic}」。\n"
        "请按如下格式整理：\n"
        "- 论文标题（arXiv ID）：一句话摘要（作者缩写）\n"
        "每条不超过 60 字。最后写 2-3 句该子领域当前研究焦点的判断。\n\n"
        "原始内容：\n{content}"
    ),
    "blog": (
        "以下是顶级 AI 研究机构的最新博客/研究页面抓取文本，主题「{topic}」。\n"
        "请提取：\n"
        "- 各机构最新公开的工作名称及一句话描述\n"
        "- 若提及具体模型、方法或重大发布，加 🔥 标注\n"
        "- 若提及技术细节（如参数量、基准成绩），请保留数字\n\n"
        "原始内容：\n{content}"
    ),
    "conference": (
        "以下是顶级学术会议官网的抓取文本，主题「{topic}」。\n"
        "请提取：\n"
        "- 最新 Call for Papers、重要 Deadline\n"
        "- 已公布的 Keynote / Invited Talks\n"
        "- 与主题相关的 Workshop / Tutorial\n\n"
        "原始内容：\n{content}"
    ),
    "aggregator": (
        "以下是权威资讯聚合平台内容，主题「{topic}」。\n"
        "请提取 3-5 条最值得关注的研究进展或 SOTA 记录更新，"
        "每条注明来源链接（若有）。\n\n"
        "原始内容：\n{content}"
    ),
}

_SYNTHESIS_PROMPT = """\
你是顶级 AI 研究分析师，擅长综合多源权威信息形成深度判断。
请基于以下来自权威信源的分类摘要，围绕主题「{topic}」撰写综合分析，结构如下：

**一、本期核心议题**（列举 3-5 个技术焦点，每个附一句判断）

**二、重大突破 / 重要发布**（具体事件，注明来源机构，保留数字/模型名）

**三、机构布局对比**（头部机构各自侧重什么方向？谁在加速？谁在转向？）

**四、建议追踪**（3-5 项具体论文或项目，附简要理由）

**五、下一步观察点**（未来 1-3 个月值得关注的研究走向）

各类信源摘要：
{summaries}
"""


def _is_valid_content(text: str) -> bool:
    if not text:
        return False
    invalid_markers = ("页面内容为空", "响应体过大", "非文本资源", "web_fetch 仅允许")
    return not any(m in text for m in invalid_markers)


class FrontierReportSkill(BaseSkill):
    """
    权威信源前沿报告技能。

    Phase 1 — SourceRegistry 按主题 + 类别选取激活信源（arXiv + 顶级机构博客 + 顶会 + 聚合器）
    Phase 2 — web_fetch 顺序抓取各信源内容，记录成功/失败日志
    Phase 3 — LLM 对每类信源分别精炼摘要，最终合并生成结构化权威报告
    """

    name: str = "frontier_report"
    description: str = (
        "基于内嵌的权威信源注册表（顶会 / 顶级 AI 实验室 / arXiv 分类流 / 权威聚合平台），"
        "抓取最新学术与产业前沿资讯，生成注明信源可信度的结构化研究简报。"
        "与 arxiv_frontier_report 的区别：本技能使用固定权威信源库而非单一 arXiv 检索，"
        "覆盖 OpenAI / DeepMind / Anthropic 等顶级机构的最新动态及顶会信息。"
        "参数：topic（报告主题），categories（可选领域标签），"
        "max_sources（信源数量，默认 8），max_chars_per_source（每源字符数，默认 4000），"
        "min_priority（最低权威等级 1-5，默认 3），arxiv_max_results（arXiv 论文条数，默认 12）"
    )
    skill_type: str = "chain"
    version: str = "1.0.0"
    args_model: ClassVar[type[BaseModel]] = FrontierReportArgs

    llm: Any = None
    web_fetch: Any = None

    def execute(
        self,
        topic: str,
        categories: list[str] | None = None,
        max_sources: int = 8,
        max_chars_per_source: int = 4000,
        min_priority: int = 3,
        arxiv_max_results: int = 12,
        **kwargs,
    ) -> str:
        if self.llm is None:
            return "FrontierReportSkill 需要注入 LLM 实例。"
        if self.web_fetch is None:
            return "FrontierReportSkill 需要注入 web_fetch 工具。"

        cats = categories or []
        registry = SourceRegistry()

        # ── Phase 1: 选取激活信源 ────────────────────────────────────────────
        # 按 max_sources 分配各类信源配额（arxiv 40%，blog 40%，conf 15%，agg 5%）
        n_total = max_sources
        n_arxiv = max(1, n_total * 4 // 10)
        n_blogs = max(1, n_total * 4 // 10)
        n_conf  = max(1, n_total * 15 // 100)
        n_agg   = max(0, n_total - n_arxiv - n_blogs - n_conf)

        selected: list[AuthoritySource] = registry.select(
            topic=topic,
            categories=cats,
            max_arxiv=n_arxiv,
            max_blogs=n_blogs,
            max_conferences=n_conf,
            max_aggregators=n_agg,
            min_priority=min_priority,
        )[:max_sources]

        pipeline_map = registry.render_pipeline_map(selected)

        # ── Phase 2: 抓取各信源内容 ──────────────────────────────────────────
        fetched: dict[str, list[tuple[AuthoritySource, str]]] = {
            "arxiv": [], "blog": [], "conference": [], "aggregator": [],
        }
        fetch_log: list[str] = []

        for src in selected:
            url = registry.build_fetch_url(src, topic, max_results=arxiv_max_results)
            raw = self.web_fetch.execute(url=url, max_chars=max_chars_per_source)
            if _is_valid_content(raw):
                fetched[src.kind].append((src, raw))
                fetch_log.append(f"✓ {src.name}")
            else:
                fetch_log.append(f"✗ {src.name}（内容为空或被拒绝）")

        total_fetched = sum(len(v) for v in fetched.values())
        if total_fetched == 0:
            return (
                f"## 权威信源前沿报告：{topic}\n\n"
                "⚠️ 未能从任何信源成功抓取内容，请检查网络连接。\n\n"
                "**激活信源**\n" + pipeline_map + "\n\n"
                "**抓取日志**\n" + " · ".join(fetch_log)
            )

        # ── Phase 3: 分类精炼 + 综合分析 ────────────────────────────────────
        kind_order: list[SourceKind] = ["arxiv", "blog", "conference", "aggregator"]
        section_parts: list[str] = []
        all_summaries: list[str] = []

        for kind in kind_order:
            items = fetched[kind]
            if not items:
                continue

            combined_content = "\n\n---\n\n".join(
                f"【{src.institution} — {src.name}】\n{content}"
                for src, content in items
            )
            prompt = _KIND_PROMPT[kind].format(
                topic=topic,
                content=combined_content[:18000],
            )
            summary = self.llm.generate(prompt)

            heading = _KIND_HEADING[kind]
            section_parts.append(f"{heading}\n\n{summary}")
            all_summaries.append(f"【{_KIND_HEADING[kind].replace('### ', '')}】\n{summary}")

        synthesis_prompt = _SYNTHESIS_PROMPT.format(
            topic=topic,
            summaries="\n\n".join(all_summaries)[:16000],
        )
        synthesis = self.llm.generate(synthesis_prompt)

        # ── 组装报告 ─────────────────────────────────────────────────────────
        header = "\n".join([
            f"## 权威信源前沿报告：{topic}",
            "",
            f"**激活信源**：{len(selected)} 个　"
            f"**成功抓取**：{total_fetched} 个　"
            f"**最低权威等级**：{'★' * min_priority}{'☆' * (5 - min_priority)}",
            "",
            "### 信息管道地图（激活信源）",
            "",
            pipeline_map,
        ])

        body = "\n\n".join(section_parts)

        footer = "\n".join([
            "### 综合分析",
            "",
            synthesis,
            "",
            "---",
            "",
            "**抓取日志**　" + " · ".join(fetch_log),
        ])

        return "\n\n".join([header, body, footer])
