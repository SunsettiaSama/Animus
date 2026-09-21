from __future__ import annotations

import json
import time

from infra.retrieval.growth import GrowthConfig, GrowthEngine, TemplateStats
from infra.retrieval.rewriter import HitSignal, RewriteResult, TemplateRewriter
from infra.retrieval.templates import RewriteTemplate, TemplateStore
from infra.threading import ThreadRegistry


class _FakeLLM:
    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _wait_for(cond, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _res(template_id: str) -> RewriteResult:
    return RewriteResult(
        query="q", original="原文", template_id=template_id
    )


def setup_function() -> None:
    ThreadRegistry.reset()


def teardown_function() -> None:
    ThreadRegistry.reset()


def _small_cfg(**kw) -> GrowthConfig:
    defaults = dict(
        enabled=True,
        authoring_enabled=True,
        hit_threshold=0.5,
        min_samples=3,
        cooldown_minutes=0.0,
        retire_threshold=0.05,
        max_templates=8,
    )
    defaults.update(kw)
    return GrowthConfig(**defaults)


def test_stats_accumulate_on_report():
    store = TemplateStore()
    growth = GrowthEngine(store, cfg=_small_cfg())
    growth.note_use("builtin.remember_q")
    growth.note_use("builtin.remember_q")
    growth.report(_res("builtin.remember_q"), [HitSignal("a", 0.6)])
    growth.report(_res("builtin.remember_q"), [HitSignal("a", 0.4)])
    stats = growth.stats_for("builtin.remember_q")
    assert stats is not None
    assert stats["uses"] == 2
    assert stats["reports"] == 2
    assert abs(stats["score_sum"] - 1.0) < 1e-6


def test_low_hits_trigger_llm_authoring_and_new_template_usable(tmp_path):
    store = TemplateStore(tmp_path / "templates.json")
    llm = _FakeLLM(
        [
            json.dumps(
                {
                    "name": "居住地问句",
                    "patterns": [r"(?:住在|家在)(.+?)(?:吗|呢|$)"],
                    "drop_words": ["其实"],
                    "frame": "recall",
                },
                ensure_ascii=False,
            )
        ]
    )
    growth = GrowthEngine(store, llm=llm, cfg=_small_cfg())
    try:
        for _ in range(4):
            growth.report(_res("builtin.remember_q"), [])  # 全部 NO_HITS
        assert _wait_for(lambda: len(llm.prompts) == 1)
        assert _wait_for(lambda: len(store.grown_templates()) == 1)
        # 新模板立即进入匹配链
        rw = TemplateRewriter(store)
        res = rw.rewrite("你家在杭州吗")
        assert res.template_id.startswith("grown.")
        assert "杭州" in res.entities
    finally:
        growth.stop()


def test_invalid_template_output_rejected():
    store = TemplateStore()
    llm = _FakeLLM(["完全不是 JSON", '{"name":"无捕获","patterns":["拉面"]}'])
    growth = GrowthEngine(store, llm=llm, cfg=_small_cfg())
    try:
        for _ in range(4):
            growth.report(_res("builtin.remember_q"), [])
        assert _wait_for(lambda: len(llm.prompts) >= 1)
        assert _wait_for(lambda: growth.status()["queued"] == 0)
        assert store.grown_templates() == []  # 两次都非法，零入库
    finally:
        growth.stop()


def test_no_llm_means_no_authoring_and_no_thread():
    store = TemplateStore()
    growth = GrowthEngine(store, llm=None, cfg=_small_cfg())
    for _ in range(6):
        growth.report(_res("builtin.remember_q"), [])
    assert growth.status()["authoring"] is False
    assert growth.status()["state"] == "idle"


def test_disabled_engine_ignores_everything():
    store = TemplateStore()
    growth = GrowthEngine(store, cfg=_small_cfg(enabled=False))
    growth.note_use("t")
    growth.report(_res("t"), [HitSignal("a", 0.9)])
    assert growth.stats_for("t") is None


def test_grown_template_retired_on_persistent_bad_stats():
    store = TemplateStore()
    store.add(
        RewriteTemplate(
            template_id="grown.bad",
            name="bad",
            source="grown",
            patterns=(r"(坏模板)(.+)",),
        )
    )
    growth = GrowthEngine(store, llm=None, cfg=_small_cfg(min_samples=2, retire_threshold=0.5))
    for _ in range(5):
        growth.report(_res("grown.bad"), [])  # avg=0 < retire_threshold
    assert store.get("grown.bad") is None
    assert "grown.bad" not in [t.template_id for t in store.active_templates()]


def test_stats_persistence_roundtrip(tmp_path):
    from pathlib import Path

    path = tmp_path / "growth_stats.json"
    store = TemplateStore()
    growth = GrowthEngine(store, cfg=_small_cfg(), stats_path=str(path))
    growth.report(_res("builtin.remember_q"), [HitSignal("a", 0.5)])
    assert path.is_file()

    growth2 = GrowthEngine(store, cfg=_small_cfg(), stats_path=str(path))
    stats = growth2.stats_for("builtin.remember_q")
    assert stats is not None and stats["reports"] == 1


def test_parse_template_requires_capture_group():
    store = TemplateStore()
    llm = _FakeLLM([])
    growth = GrowthEngine(store, llm=llm, cfg=_small_cfg())
    no_capture = growth._parse_template('{"name":"x","patterns":["只有词面"],"drop_words":[]}')
    assert no_capture is None
    bad_regex = growth._parse_template('{"name":"x","patterns":["(unclosed(.+"],"drop_words":[]}')
    assert bad_regex is None
    ok = growth._parse_template(
        '{"name":"x","patterns":["(哪一年)(.+)"],"drop_words":[],"frame":"time"}'
    )
    assert ok is not None and ok.compiled


def test_template_stats_roundtrip():
    stats = TemplateStats(uses=3, reports=2, hit_count=1, score_sum=0.8)
    cloned = TemplateStats.from_dict(stats.to_dict())
    assert cloned == stats
    assert cloned.avg_score == 0.4
