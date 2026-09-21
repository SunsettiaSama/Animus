from __future__ import annotations

from infra.retrieval.rewriter import HitSignal, TemplateRewriter
from infra.retrieval.templates import RewriteTemplate, TemplateStore


class _FakeGrowth:
    def __init__(self) -> None:
        self.uses: list[str] = []
        self.reports: list[tuple[str, list[HitSignal]]] = []

    def note_use(self, template_id: str) -> None:
        self.uses.append(template_id)

    def report(self, result, hits) -> None:
        self.reports.append((result.template_id, list(hits)))


def _rewriter(growth=None) -> TemplateRewriter:
    return TemplateRewriter(TemplateStore(), growth=growth)


def test_remember_frame_strips_and_captures_entity():
    res = _rewriter().rewrite("你还记得我们上次一起去的那家拉面店吗")
    assert res.template_id == "builtin.remember_q"
    assert res.frame == "recall"
    assert "我们上次一起去的那家拉面店" in res.entities
    assert "还记得" not in res.query
    assert "吗" not in res.query
    assert "拉面" in res.terms


def test_single_char_content_words_kept():
    # 回归：min_term_len 曾把单字内容词（养/猫）丢掉
    res = _rewriter().rewrite("你说过你养了一只猫")
    assert "猫" in res.terms
    assert "猫" in res.entities


def test_time_window_extracted():
    res = _rewriter().rewrite("还记得上周去的地方吗")
    assert res.time_window in ("last_week", "recent")
    assert isinstance(res.time_window_days, int)
    res2 = _rewriter().rewrite("你觉得这个方案怎么样")
    assert res2.time_window == ""


def test_fully_stripped_text_falls_back_to_original():
    # 剥框架后为空（整句都是框架词）→ 回退原文，绝不产出空 query
    res = _rewriter().rewrite("还记得吗")
    assert res.used_original_fallback is True
    assert res.query == "还记得吗"
    # 普通句子：query 保留剥框架后的表层，不再丢词拼串
    res2 = _rewriter().rewrite("你说过你养了一只猫")
    assert res2.used_original_fallback is False
    assert "你养了一只猫" in res2.query
    assert "猫" in res2.terms


def test_blank_input_returns_empty():
    res = _rewriter().rewrite("   ")
    assert res.query == ""


def test_determinism_and_cache():
    rw = _rewriter()
    a = rw.rewrite("还记得上次那家店吗")
    b = rw.rewrite("还记得上次那家店吗")
    assert a == b  # dataclass 相等 + 命中缓存


def test_verify_intent_overrides_frame():
    res = _rewriter().rewrite("你说过你养了一只猫", intent="verify")
    assert res.frame == "verify"


def test_report_forwards_to_growth():
    growth = _FakeGrowth()
    rw = _rewriter(growth=growth)
    res = rw.rewrite("还记得那只猫吗")
    assert growth.uses == [res.template_id]
    rw.report(res, [HitSignal(id="m1", score=0.8)])
    assert growth.reports[0][0] == res.template_id


def test_report_swallows_growth_errors():
    class _Boom:
        def note_use(self, tid):
            raise RuntimeError("boom")

        def report(self, result, hits):
            raise RuntimeError("boom")

    rw = _rewriter(growth=_Boom())
    res = rw.rewrite("还记得那只猫吗")  # 不 raise
    rw.report(res, [])  # 不 raise


def test_grown_template_joins_matching_chain():
    store = TemplateStore()
    store.add(
        RewriteTemplate(
            template_id="grown.city",
            name="city",
            source="grown",
            patterns=(r"(?:住在|家在)(.+?)(?:吗|呢|$)",),
            frame="recall",
        )
    )
    rw = TemplateRewriter(store)
    res = rw.rewrite("你之前家在杭州吗")
    assert res.template_id == "grown.city"
    assert "杭州" in res.entities
