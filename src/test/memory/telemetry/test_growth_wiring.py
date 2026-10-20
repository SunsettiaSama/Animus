"""R5.5 growth 生产接线锁：统计先行、无 LLM、authoring 默认关、report 异常不外溢。"""
from __future__ import annotations

import json

import pytest

import infra.retrieval as retrieval_pkg
from config.infra.retrieval_config import RetrievalConfig, RewriterConfig, WalkOptions
from infra.retrieval import get_default_rewriter
from infra.retrieval.growth import GrowthConfig


@pytest.fixture()
def isolated_default_rewriter(tmp_path, monkeypatch):
    """把默认 rewriter 指到 tmp store_root，测完复位进程级单例。"""
    from infra.retrieval.locate import LocatorConfig
    import config.infra.retrieval_config as rc

    monkeypatch.setattr(retrieval_pkg, "_DEFAULT_REWRITER", None, raising=True)
    monkeypatch.setattr(
        rc.RetrievalConfig,
        "load_default",
        classmethod(
            lambda cls, path=None: RetrievalConfig(
                rewriter=RewriterConfig(enabled=True),
                growth=GrowthConfig(enabled=True, authoring_enabled=False),
                locator=LocatorConfig(),
                walk=WalkOptions(),
                store_root=str(tmp_path / "retrieval"),
            )
        ),
    )
    yield tmp_path / "retrieval"
    monkeypatch.setattr(retrieval_pkg, "_DEFAULT_REWRITER", None, raising=True)


def test_default_rewriter_has_growth_stats_no_llm(isolated_default_rewriter):
    rewriter = get_default_rewriter()
    assert rewriter is not None
    growth = rewriter._growth
    assert growth is not None, "生产 rewriter 必须带 growth 统计（R4.1）"
    assert growth._llm is None, "生产不注入 LLM（authoring 关闭）"
    assert not growth.cfg.authoring_enabled, "authoring 默认关（R4.2）"
    assert str(isolated_default_rewriter / "growth_stats.json") == growth._stats_path


def test_report_accumulates_and_persists(isolated_default_rewriter):
    from infra.retrieval import HitSignal

    rewriter = get_default_rewriter()
    rr = rewriter.rewrite("你还记得那家拉面店吗")
    assert rr.template_id
    rewriter.report(rr, [HitSignal(id="n1", score=0.8)])

    stats_path = isolated_default_rewriter / "growth_stats.json"
    assert stats_path.exists(), "统计必须落盘 growth_stats.json"
    data = json.loads(stats_path.read_text(encoding="utf-8"))
    assert rr.template_id in data
    assert data[rr.template_id]["reports"] == 1
    assert data[rr.template_id]["hit_count"] == 1


def test_report_exception_does_not_affect_rewriter(isolated_default_rewriter):
    rewriter = get_default_rewriter()
    rr = rewriter.rewrite("你还记得那家拉面店吗")

    class _BoomSignal:
        pass

    rewriter.report(rr, [_BoomSignal()])  # 非法 hits 不应抛异常
    rr2 = rewriter.rewrite("上次我们聊的那个话题怎么样了")
    assert rr2.query


def test_default_authoring_flags_off():
    """配置层默认值：growth.enabled=True、authoring_enabled=False。"""
    cfg = GrowthConfig()
    assert cfg.enabled is True
    assert cfg.authoring_enabled is False
    parsed = RetrievalConfig.from_dict({})
    assert parsed.growth.authoring_enabled is False
    assert parsed.growth.enabled is True


def test_disabled_growth_yields_none_engine(tmp_path, monkeypatch):
    from infra.retrieval.locate import LocatorConfig

    monkeypatch.setattr(retrieval_pkg, "_DEFAULT_REWRITER", None, raising=True)
    import config.infra.retrieval_config as rc

    monkeypatch.setattr(
        rc.RetrievalConfig,
        "load_default",
        classmethod(
            lambda cls, path=None: RetrievalConfig(
                rewriter=RewriterConfig(enabled=True),
                growth=GrowthConfig(enabled=False),
                locator=LocatorConfig(),
                walk=WalkOptions(),
                store_root=str(tmp_path),
            )
        ),
    )
    try:
        rewriter = get_default_rewriter()
        assert rewriter is not None
        assert rewriter._growth is None, "growth.enabled=false → 不构造引擎（死配置零开销）"
    finally:
        monkeypatch.setattr(retrieval_pkg, "_DEFAULT_REWRITER", None, raising=True)
