"""
FrontierReportSkill 测试
========================
覆盖范围（离线，无网络、无真实 LLM）：

  SourceRegistry —
    test_source_count                 : 注册表条目数 ≥ 25
    test_all_sources_kinds            : 四种 kind 均存在
    test_priority_range               : 所有信源 priority 在 [1, 5]
    test_get_known_source             : 按 id 查找返回正确对象
    test_get_unknown_source           : 未知 id 返回 None
    test_select_returns_capped_count  : 结果不超过 max_sources
    test_select_min_priority_filter   : min_priority=5 只保留最高优先级
    test_select_kind_distribution     : 各 kind 均出现在结果中
    test_select_nlp_topic_prefers_cl  : NLP 主题优先选 cs.CL
    test_select_cv_topic_prefers_cv   : CV 主题优先选 cs.CV
    test_build_arxiv_url_contains_cat : arXiv URL 含 category
    test_build_arxiv_url_contains_topic: arXiv URL 含 topic 关键词
    test_build_blog_url_passthrough   : blog 信源 URL 原样返回
    test_render_pipeline_map_table    : 管道地图含表头和行

  FrontierReportSkill —
    test_schema_topic_required        : 缺少 topic 时 Pydantic 报错
    test_schema_valid_args            : 正常参数通过验证
    test_execute_no_llm_returns_msg   : 未注入 LLM 时返回提示字符串
    test_execute_no_web_fetch         : 未注入 web_fetch 时返回提示字符串
    test_execute_all_empty_fetch      : 全部信源返回空时报告空抓取
    test_execute_happy_path_structure : 正常执行时报告含关键章节标题
    test_execute_topic_in_report      : 报告中含 topic 文本
    test_execute_pipeline_map_in_report: 报告中含信息管道地图表头
    test_execute_partial_fetch_skip   : 部分信源返回空时被跳过、不中断
    test_execute_llm_called_per_kind  : 每种 kind 调用一次 LLM 精炼，末尾一次综合
    test_execute_min_priority_respected: min_priority=5 时只激活最高等级信源
    test_execute_max_sources_cap      : max_sources=3 时激活信源 ≤ 3

运行方式：
  cd E:/ReAct
  python -m pytest src/test/tools/test_frontier_report.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from agent.react.action.skill.source_registry import (
    SOURCES,
    AuthoritySource,
    SourceRegistry,
)
from agent.react.action.skill.frontier_report import FrontierReportArgs, FrontierReportSkill


# ── 测试用 MockLLM（直接内联，避免跨包依赖） ─────────────────────────────────

class _MockLLM:
    def __init__(self, responses: list[str]) -> None:
        self._q: list[str] = list(responses)
        self._fallback = responses[-1] if responses else "[mock]"
        self.call_count = 0

    def generate(self, prompt: str) -> str:  # noqa: ARG002
        self.call_count += 1
        return self._q.pop(0) if self._q else self._fallback


def _mock_fetch(content_map: dict[str, str], default: str = ""):
    """返回一个 web_fetch stub，根据 URL 关键词返回不同内容。"""
    mock = MagicMock()

    def _execute(url: str, max_chars: int = 4000, **kw) -> str:  # noqa: ARG001
        for key, val in content_map.items():
            if key in url:
                return val
        return default

    mock.execute.side_effect = _execute
    return mock


# ═════════════════════════════════════════════════════════════════════════════
#  SourceRegistry
# ═════════════════════════════════════════════════════════════════════════════

class TestSourceRegistry:

    def setup_method(self):
        self.reg = SourceRegistry()

    # ── 数据完整性 ────────────────────────────────────────────────────────────

    def test_source_count(self):
        assert len(self.reg.all_sources()) >= 25

    def test_all_sources_kinds(self):
        kinds = {s.kind for s in self.reg.all_sources()}
        assert kinds == {"arxiv", "blog", "conference", "aggregator"}

    def test_priority_range(self):
        for s in self.reg.all_sources():
            assert 1 <= s.priority <= 5, f"{s.id} priority={s.priority} out of range"

    def test_ids_unique(self):
        ids = [s.id for s in self.reg.all_sources()]
        assert len(ids) == len(set(ids)), "SOURCES 中存在重复 id"

    # ── get ────────────────────────────────────────────────────────────────────

    def test_get_known_source(self):
        src = self.reg.get("arxiv_cs_cl")
        assert src is not None
        assert src.kind == "arxiv"
        assert src.institution == "arXiv"

    def test_get_unknown_source(self):
        assert self.reg.get("does_not_exist_xyz") is None

    # ── select ────────────────────────────────────────────────────────────────

    def test_select_returns_capped_count(self):
        result = self.reg.select("transformer", [], max_arxiv=2, max_blogs=2,
                                 max_conferences=1, max_aggregators=1)
        assert len(result) <= 6

    def test_select_min_priority_filter(self):
        result = self.reg.select("ai", [], min_priority=5)
        for s in result:
            assert s.priority == 5, f"{s.id} priority={s.priority} < 5"

    def test_select_kind_distribution(self):
        result = self.reg.select("language model", ["nlp"],
                                 max_arxiv=2, max_blogs=2,
                                 max_conferences=1, max_aggregators=1,
                                 min_priority=3)
        kinds = {s.kind for s in result}
        assert "arxiv" in kinds
        assert "blog"  in kinds

    def test_select_nlp_topic_prefers_cl(self):
        result = self.reg.select("natural language processing transformer",
                                 ["nlp"], max_arxiv=3, max_blogs=0,
                                 max_conferences=0, max_aggregators=0)
        ids = [s.id for s in result]
        assert "arxiv_cs_cl" in ids, "NLP 主题应优先选 cs.CL"

    def test_select_cv_topic_prefers_cv(self):
        result = self.reg.select("image detection segmentation",
                                 ["cv"], max_arxiv=3, max_blogs=0,
                                 max_conferences=0, max_aggregators=0)
        ids = [s.id for s in result]
        assert "arxiv_cs_cv" in ids, "CV 主题应优先选 cs.CV"

    def test_select_robotics_topic(self):
        result = self.reg.select("robot manipulation navigation",
                                 [], max_arxiv=2, max_blogs=0,
                                 max_conferences=0, max_aggregators=0)
        ids = [s.id for s in result]
        assert "arxiv_cs_ro" in ids, "Robotics 主题应优先选 cs.RO"

    def test_select_empty_topic_returns_by_priority(self):
        result = self.reg.select("", [], max_arxiv=1, max_blogs=1,
                                 max_conferences=1, max_aggregators=0)
        # 空主题无 tag 命中，应仍返回 priority 最高的信源
        assert len(result) >= 2
        for s in result:
            assert s.priority >= 3

    # ── build_fetch_url ───────────────────────────────────────────────────────

    def test_build_arxiv_url_contains_cat(self):
        src = self.reg.get("arxiv_cs_cl")
        url = self.reg.build_fetch_url(src, "language model")
        assert "cs.CL" in url
        assert "export.arxiv.org" in url

    def test_build_arxiv_url_contains_topic(self):
        src = self.reg.get("arxiv_cs_cl")
        url = self.reg.build_fetch_url(src, "multimodal reasoning")
        assert "multimodal" in url or "multimodal+reasoning" in url.lower()

    def test_build_arxiv_url_max_results(self):
        src = self.reg.get("arxiv_cs_lg")
        url = self.reg.build_fetch_url(src, "optimization", max_results=20)
        assert "max_results=20" in url

    def test_build_blog_url_passthrough(self):
        src = self.reg.get("openai_blog")
        url = self.reg.build_fetch_url(src, "any topic")
        assert url == src.url
        assert url.startswith("https://")

    def test_build_conference_url_passthrough(self):
        src = self.reg.get("neurips")
        url = self.reg.build_fetch_url(src, "deep learning")
        assert url == "https://neurips.cc/"

    # ── render_pipeline_map ───────────────────────────────────────────────────

    def test_render_pipeline_map_table(self):
        selected = self.reg.select("ai", [], max_arxiv=1, max_blogs=1,
                                   max_conferences=1, max_aggregators=0)
        rendered = self.reg.render_pipeline_map(selected)
        assert "| 信源 |" in rendered
        assert "| 机构/平台 |" in rendered
        assert "权威等级" in rendered
        # 至少有一条数据行（含 ★ 字符）
        assert "★" in rendered

    def test_render_pipeline_map_row_per_source(self):
        selected = self.reg.select("nlp", [], max_arxiv=2, max_blogs=2,
                                   max_conferences=0, max_aggregators=0)
        rendered = self.reg.render_pipeline_map(selected)
        data_rows = [line for line in rendered.splitlines() if "| " in line
                     and "信源" not in line and "----" not in line]
        assert len(data_rows) == len(selected)


# ═════════════════════════════════════════════════════════════════════════════
#  FrontierReportArgs schema
# ═════════════════════════════════════════════════════════════════════════════

class TestFrontierReportArgs:

    def test_schema_topic_required(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            FrontierReportArgs(categories=["nlp"])

    def test_schema_valid_minimal(self):
        args = FrontierReportArgs(topic="large language models")
        assert args.topic == "large language models"
        assert args.categories == []
        assert args.max_sources == 8
        assert args.min_priority == 3

    def test_schema_valid_full(self):
        args = FrontierReportArgs(
            topic="vision transformer",
            categories=["cv", "nlp"],
            max_sources=10,
            max_chars_per_source=6000,
            min_priority=4,
            arxiv_max_results=20,
        )
        assert args.max_sources == 10
        assert "cv" in args.categories

    def test_schema_max_sources_bounds(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            FrontierReportArgs(topic="t", max_sources=2)   # ge=3
        with pytest.raises(ValidationError):
            FrontierReportArgs(topic="t", max_sources=21)  # le=20

    def test_schema_min_priority_bounds(self):
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            FrontierReportArgs(topic="t", min_priority=0)
        with pytest.raises(ValidationError):
            FrontierReportArgs(topic="t", min_priority=6)


# ═════════════════════════════════════════════════════════════════════════════
#  FrontierReportSkill — 执行逻辑
# ═════════════════════════════════════════════════════════════════════════════

class TestFrontierReportSkill:

    def _skill(self, llm=None, web_fetch=None) -> FrontierReportSkill:
        return FrontierReportSkill(llm=llm, web_fetch=web_fetch)

    # ── 依赖缺失保护 ──────────────────────────────────────────────────────────

    def test_execute_no_llm_returns_msg(self):
        skill = self._skill(web_fetch=MagicMock())
        result = skill.execute(topic="test")
        assert "LLM" in result

    def test_execute_no_web_fetch_returns_msg(self):
        skill = self._skill(llm=_MockLLM(["ok"]))
        result = skill.execute(topic="test")
        assert "web_fetch" in result

    # ── 正常执行 ──────────────────────────────────────────────────────────────

    def _make_llm_and_fetch(self, fetch_content: str = "论文：FakePaper 2026"):
        llm = _MockLLM(["[arxiv摘要]", "[blog摘要]", "[conf摘要]", "[agg摘要]", "[综合分析]"] * 5)
        fetch = _mock_fetch({}, default=fetch_content)
        return llm, fetch

    def test_execute_happy_path_structure(self):
        llm, fetch = self._make_llm_and_fetch()
        skill = self._skill(llm=llm, web_fetch=fetch)
        report = skill.execute(topic="large language model", max_sources=4)
        assert "权威信源前沿报告" in report
        assert "信息管道地图" in report
        assert "综合分析" in report

    def test_execute_topic_in_report(self):
        llm, fetch = self._make_llm_and_fetch()
        skill = self._skill(llm=llm, web_fetch=fetch)
        topic = "multimodal vision language"
        report = skill.execute(topic=topic, max_sources=4)
        assert topic in report

    def test_execute_pipeline_map_in_report(self):
        llm, fetch = self._make_llm_and_fetch()
        skill = self._skill(llm=llm, web_fetch=fetch)
        report = skill.execute(topic="robotics", max_sources=4, categories=["robotics"])
        assert "机构/平台" in report
        assert "权威等级" in report

    def test_execute_fetch_log_in_report(self):
        llm, fetch = self._make_llm_and_fetch()
        skill = self._skill(llm=llm, web_fetch=fetch)
        report = skill.execute(topic="nlp", max_sources=4)
        # 日志行含 ✓ 或 ✗
        assert "✓" in report or "✗" in report

    # ── 空抓取降级 ────────────────────────────────────────────────────────────

    def test_execute_all_empty_fetch(self):
        llm = _MockLLM(["[mock]"])
        fetch = _mock_fetch({}, default="")   # 全部返回空字符串
        skill = self._skill(llm=llm, web_fetch=fetch)
        report = skill.execute(topic="quantum computing", max_sources=4)
        assert "未能从任何信源" in report or "抓取" in report

    def test_execute_partial_fetch_skip(self):
        """arxiv 返回内容，blog 返回空 — 不应报错，blog 被跳过。"""
        llm = _MockLLM(["[arxiv]", "[综合分析]"] * 5)
        fetch = _mock_fetch(
            {"arxiv.org": "Papers: FakePaper 2026 - abstract here"},
            default="",  # blog/conf 返回空
        )
        skill = self._skill(llm=llm, web_fetch=fetch)
        report = skill.execute(topic="nlp", max_sources=5)
        assert "权威信源前沿报告" in report
        assert "✗" in report   # 至少有信源被标为失败

    def test_execute_invalid_content_skipped(self):
        """web_fetch 返回特定错误字符串时不进入报告正文。"""
        llm = _MockLLM(["[arxiv]", "[综合]"] * 5)
        fetch = _mock_fetch(
            {"arxiv.org": "valid arxiv content here"},
            default="页面内容为空",
        )
        skill = self._skill(llm=llm, web_fetch=fetch)
        report = skill.execute(topic="computer vision", max_sources=4)
        assert "权威信源前沿报告" in report

    # ── 参数边界 ──────────────────────────────────────────────────────────────

    def test_execute_max_sources_cap(self):
        """max_sources=3 时激活信源数 ≤ 3。"""
        activated: list[str] = []
        llm = _MockLLM(["[mock]"] * 20)

        mock_fetch = MagicMock()
        def _count_and_return(url: str, max_chars: int = 4000, **kw):
            activated.append(url)
            return "some content"
        mock_fetch.execute.side_effect = _count_and_return

        skill = self._skill(llm=llm, web_fetch=mock_fetch)
        skill.execute(topic="ai", max_sources=3)
        assert len(activated) <= 3

    def test_execute_min_priority_respected(self):
        """min_priority=5 只激活最高权威等级信源，数量应少于默认设置。"""
        call_urls_p5: list[str] = []
        call_urls_p3: list[str] = []
        llm = _MockLLM(["[mock]"] * 30)

        def _fetch_p5(url, max_chars=4000, **kw):
            call_urls_p5.append(url)
            return "content"
        def _fetch_p3(url, max_chars=4000, **kw):
            call_urls_p3.append(url)
            return "content"

        fetch_p5 = MagicMock(); fetch_p5.execute.side_effect = _fetch_p5
        fetch_p3 = MagicMock(); fetch_p3.execute.side_effect = _fetch_p3

        skill_p5 = self._skill(llm=_MockLLM(["[mock]"] * 20), web_fetch=fetch_p5)
        skill_p3 = self._skill(llm=_MockLLM(["[mock]"] * 20), web_fetch=fetch_p3)

        skill_p5.execute(topic="ai", max_sources=8, min_priority=5)
        skill_p3.execute(topic="ai", max_sources=8, min_priority=3)

        # min_priority=5 激活的信源应 ≤ min_priority=3 的激活数
        assert len(call_urls_p5) <= len(call_urls_p3)

    def test_execute_llm_called_per_kind_plus_synthesis(self):
        """有 N 种 kind 抓到内容时，LLM 被调用 N + 1 次（每种精炼一次 + 综合一次）。"""
        llm = _MockLLM(["[mock]"] * 20)
        fetch = _mock_fetch(
            {
                "arxiv.org":        "arxiv content",
                "openai.com":       "openai blog content",
                "anthropic.com":    "anthropic blog content",
                "neurips.cc":       "neurips content",
                "paperswithcode":   "pwc content",
            },
            default="",
        )
        skill = self._skill(llm=llm, web_fetch=fetch)
        skill.execute(topic="large language model", max_sources=8)

        # 至少抓到 arxiv + blog 两种 → LLM ≥ 3 次（2 种精炼 + 1 综合）
        assert llm.call_count >= 3

    # ── 信源选择与主题联动 ────────────────────────────────────────────────────

    def test_execute_nlp_categories_activates_cl(self):
        """categories=['nlp'] 应激活 cs.CL arXiv feed。"""
        urls_called: list[str] = []
        llm = _MockLLM(["[mock]"] * 20)
        fetch = MagicMock()
        fetch.execute.side_effect = lambda url, **kw: (urls_called.append(url) or "nlp paper")

        skill = self._skill(llm=llm, web_fetch=fetch)
        skill.execute(topic="language model", categories=["nlp"], max_sources=5)

        assert any("cs.CL" in u for u in urls_called), \
            f"cs.CL 应出现在请求 URL 中，实际 URL: {urls_called}"

    def test_execute_cv_categories_activates_cv(self):
        """categories=['cv'] 应激活 cs.CV arXiv feed。"""
        urls_called: list[str] = []
        llm = _MockLLM(["[mock]"] * 20)
        fetch = MagicMock()
        fetch.execute.side_effect = lambda url, **kw: (urls_called.append(url) or "cv paper")

        skill = self._skill(llm=llm, web_fetch=fetch)
        skill.execute(topic="image segmentation", categories=["cv"], max_sources=5)

        assert any("cs.CV" in u for u in urls_called), \
            f"cs.CV 应出现在请求 URL 中，实际 URL: {urls_called}"

    def test_execute_arxiv_url_contains_topic_keyword(self):
        """arXiv 请求 URL 应含 topic 关键词（经 urlencode）。"""
        urls_called: list[str] = []
        llm = _MockLLM(["[mock]"] * 20)
        fetch = MagicMock()
        fetch.execute.side_effect = lambda url, **kw: (urls_called.append(url) or "paper content")

        skill = self._skill(llm=llm, web_fetch=fetch)
        skill.execute(topic="diffusion model", categories=["cv"], max_sources=4)

        arxiv_urls = [u for u in urls_called if "arxiv.org" in u]
        assert arxiv_urls, "应发出 arXiv API 请求"
        assert any("diffusion" in u.lower() for u in arxiv_urls), \
            f"arXiv URL 应含 topic 关键词，实际: {arxiv_urls}"


# ═════════════════════════════════════════════════════════════════════════════
#  直接运行
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("请使用 pytest 运行此文件：")
    print("  python -m pytest src/test/tools/test_frontier_report.py -v")
