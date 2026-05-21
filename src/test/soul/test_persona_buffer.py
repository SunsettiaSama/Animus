from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from agent.soul.memory.unit import FactualMemory, Valence
from agent.soul.persona.buffer import cluster_memory_units, current_month
from agent.soul.persona.manager import PersonaManager


def _cluster_meta(*, theme: str = "协作犹豫", tick_id: str = "tick-1", unit_id: str = "") -> dict:
    payload = {
        "theme": theme,
        "tick_id": tick_id,
    }
    if unit_id:
        payload["unit_ids"] = [unit_id]
    return payload


def _unit(*, focus: str, fact: str = "测试事实", unit_id: str = "") -> FactualMemory:
    unit = FactualMemory(
        id=unit_id or f"u-{focus}",
        focus=focus,
        fact=fact,
        perception="有些感受",
        emotion="焦虑",
        emotion_intensity=0.4,
        valence=Valence.negative,
    )
    unit.created_at = datetime.now(timezone.utc)
    return unit


class _DriftLLM:
    _CLUSTER_JSON = json.dumps(
        {
            "theme": "协作",
            "insight": "我注意到自己在协作前会犹豫。",
            "adds": [{"content": "我会在协作前多确认一步", "strength": "emerging"}],
            "upgrades": [],
            "removes": [],
        },
        ensure_ascii=False,
    )
    _MERGE_JSON = json.dumps(
        {
            "insight": "我在协作中更常先确认再行动。",
            "adds": [],
            "upgrades": [],
            "removes": [],
        },
        ensure_ascii=False,
    )
    _REVISE_JSON = json.dumps(
        {
            "narrative": "我逐渐学会在协作前先确认预期，减少反复犹豫。",
            "adds": [{"content": "我会在协作前多确认一步", "strength": "emerging"}],
            "upgrades": [],
            "removes": [],
        },
        ensure_ascii=False,
    )

    def generate_messages(self, messages):
        content = messages[-1].content
        if "片段 A" in content:
            return self._MERGE_JSON
        if "本月蒸馏草稿" in content:
            return self._REVISE_JSON
        return self._CLUSTER_JSON


class _MemoryPort:
    def __init__(self, units):
        self._units = units

    def list_drift_units(self, *, month, anchor_unit_ids=None, limit=120):
        _ = month
        _ = anchor_unit_ids
        return list(self._units)[:limit]


def test_record_cluster_signals_via_manager(persona_cfg):
    manager = PersonaManager(persona_cfg)
    result = manager.record_cluster_signals([_cluster_meta()])

    assert result["ok"] is True
    assert result["applied"] == 1
    assert result["buffer"]["pending"] == 1
    assert manager.buffer.pending()[0].theme == "协作犹豫"

    path = os.path.join(persona_cfg.persona_dir, "experience_buffer.jsonl")
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as f:
        lines = [line for line in f if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["theme"] == "协作犹豫"


def test_rejects_empty_theme(persona_cfg):
    manager = PersonaManager(persona_cfg)
    try:
        manager.record_cluster_signals([{"theme": "", "tick_id": "x"}])
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_buffer_reload_from_disk(persona_cfg):
    manager = PersonaManager(persona_cfg)
    manager.record_cluster_signals([_cluster_meta(theme="失败反刍")])

    reloaded = PersonaManager(persona_cfg)
    assert reloaded.buffer.summary()["pending"] == 1
    assert reloaded.buffer.pending()[0].theme == "失败反刍"


def test_monthly_drift_not_due_without_force(persona_cfg):
    manager = PersonaManager(persona_cfg)
    manager.record_cluster_signals([_cluster_meta(theme="模式A")])
    manager._buffer_meta.last_drift_month = current_month()

    result = manager.run_monthly_drift()
    assert result["ok"] is True
    assert result["applied"] is False
    assert result["reason"] == "not_due"


def test_cluster_memory_units_focus_fallback():
    units = [
        _unit(focus="项目进度：延期"),
        _unit(focus="项目进度：对齐"),
        _unit(focus="协作边界"),
    ]
    clusters = cluster_memory_units(units, None)
    assert len(clusters) == 2
    themes = {c.theme for c in clusters}
    assert any("项目进度" in t for t in themes)
    assert any("协作边界" in t for t in themes)


def test_monthly_drift_skill_pipeline(persona_cfg):
    manager = PersonaManager(persona_cfg, llm=_DriftLLM())
    manager.record_cluster_signals([_cluster_meta(theme="协作", unit_id="u1")])
    units = [
        _unit(focus="协作：确认预期", unit_id="u1"),
        _unit(focus="协作：表达犹豫", unit_id="u2"),
    ]
    manager.set_memory_port(_MemoryPort(units))

    result = manager.run_monthly_drift(force=True)
    assert result["ok"] is True
    assert result["applied"] is True
    assert result["reason"] == "self_concept_drifted"
    assert result["cluster_count"] >= 1
    assert manager.self_concept.narrative.strip()
    assert manager.buffer.pending() == []


def test_monthly_drift_no_llm(persona_cfg):
    manager = PersonaManager(persona_cfg)
    manager.record_cluster_signals([_cluster_meta(theme="模式A")])
    manager.set_memory_port(_MemoryPort([_unit(focus="模式A")]))

    result = manager.run_monthly_drift(force=True)
    assert result["applied"] is False
    assert result["reason"] == "no_llm"


def test_snapshot_includes_buffer_schedule(persona_cfg):
    manager = PersonaManager(persona_cfg)
    manager.record_cluster_signals([_cluster_meta(theme="紧绷", tick_id="tick-2")])

    snap = manager.snapshot()
    assert snap["buffer"]["pending"] == 1
    assert "紧绷" in snap["buffer"]["recent_themes"]
    assert "last_drift_at" in snap["buffer"]

    detail = manager.buffer_snapshot(include_signals=True)
    assert detail["pending"] == 1
    assert len(detail["signals"]) == 1


def test_reset_self_concept_also_clears_buffer(persona_cfg):
    manager = PersonaManager(persona_cfg)
    manager.record_cluster_signals([_cluster_meta()])
    manager.reset_self_concept()
    manager._reset_self_concept_impl()

    assert manager.buffer.is_empty()
    assert manager.self_concept.is_empty()


def test_to_buffer_meta_matches_record(persona_cfg):
    from agent.soul.memory.retriever import PersonaThemeCluster, ScoredUnit

    unit = _unit(focus="项目进度", fact="讨论延期", unit_id="u1")
    cluster = PersonaThemeCluster(
        theme="项目进度",
        mass=2.0,
        units=[ScoredUnit(unit, relevance=1.0, activation=0.8)],
        cluster_key="ck1",
    )
    payload = cluster.to_buffer_meta(tick_id="hb-1")

    manager = PersonaManager(persona_cfg)
    result = manager.record_cluster_signals([payload])
    assert result["applied"] == 1
    signal = manager.buffer.pending()[0]
    assert signal.theme == "项目进度"
    assert signal.tick_id == "hb-1"
    assert signal.unit_ids == ["u1"]
    assert signal.cluster_key == "ck1"
