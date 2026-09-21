from __future__ import annotations

from random import Random

from agent.soul.speak.responders.request_driven.composer.domain.retrieve import (
    MemoryRetrievePolicy,
)
from agent.soul.speak.responders.request_driven.composer.ports.memory import MemoryUnit
from infra.retrieval.rewriter import RewriteResult


class _FakeStaging:
    def __init__(self, units):
        from types import SimpleNamespace

        self._items = [SimpleNamespace(unit=u, kind="dialogue") for u in units]

    def items(self, session_id):
        return list(self._items)


class _OverrideRewriter:
    """确定性假 rewriter：query 恒为 OVERRIDDEN，验证接线而非分词。"""

    def rewrite(self, text, *, intent="recall"):
        return RewriteResult(query="OVERRIDDEN", original=text, template_id="fake")


def _policy(units, rewriter=None):
    return MemoryRetrievePolicy(
        _FakeStaging(units),
        rng=Random(0),
        normal_ratio=1.0,  # 关掉 90/10 随机扰动，保证确定性
        min_score=0.01,    # 过滤 BM25 零分项，只看真实命中
        top_k=3,
        query_rewriter=rewriter,
    )


def test_policy_passes_rewritten_query_to_bm25():
    match = MemoryUnit(unit_id="m1", text="OVERRIDDEN 命中的记忆")
    miss = MemoryUnit(unit_id="m2", text="完全无关的内容")
    hits = _policy([match, miss], rewriter=_OverrideRewriter()).retrieve(
        "s1", primary_query="原始查询", mode="bm25"
    )
    assert [h.unit.unit_id for h in hits] == ["m1"]


def test_policy_without_rewriter_uses_raw_composed_query():
    match = MemoryUnit(unit_id="m1", text="原始查询 命中的记忆")
    hits = _policy([match]).retrieve("s1", primary_query="原始查询", mode="bm25")
    assert [h.unit.unit_id for h in hits] == ["m1"]


def test_real_template_rewriter_strips_frame_in_policy_path():
    from infra.retrieval import TemplateRewriter

    match = MemoryUnit(unit_id="m1", text="那家拉面店在巷子深处")
    hits = _policy([match], rewriter=TemplateRewriter()).retrieve(
        "s1", primary_query="你还记得那家拉面店吗", mode="bm25"
    )
    assert [h.unit.unit_id for h in hits] == ["m1"]
    # 框架词剥除后依然命中（拉面店 bigram 保留）
    miss = MemoryUnit(unit_id="m2", text="还记得还记得还记得")
    hits2 = _policy([miss], rewriter=TemplateRewriter()).retrieve(
        "s1", primary_query="你还记得那家拉面店吗", mode="bm25"
    )
    assert hits2 == []
