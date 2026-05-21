from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from agent.soul.memory.retriever import (
    MemoryRetriever,
    PersonaThemeCluster,
    PersonaThemeProfile,
    ScoredUnit,
)
from agent.soul.memory.unit import FactualMemory, MemoryTier, Valence
from agent.soul.persona.buffer.consolidation import MonthlyDriftUpdater
from agent.soul.persona.buffer.trace import ClusterSignal


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _unit(
    uid: str,
    focus: str,
    *,
    days_ago: float,
    tier: MemoryTier = MemoryTier.short_term,
    recall_count: int = 0,
    rehearsal_count: int = 0,
    narrative_ref_count: int = 0,
) -> FactualMemory:
    created = _now() - timedelta(days=days_ago)
    return FactualMemory(
        id=uid,
        focus=focus,
        fact=f"关于{focus}的事实",
        perception=f"体验{focus}",
        emotion="焦虑",
        emotion_intensity=0.6,
        valence=Valence.negative,
        tier=tier,
        recall_count=recall_count,
        rehearsal_count=rehearsal_count,
        narrative_ref_count=narrative_ref_count,
        created_at=created,
        last_accessed=created,
    )


def _retriever(units: list[FactualMemory]) -> MemoryRetriever:
    store = MagicMock()
    store.list_recent.return_value = units
    store.get_many.side_effect = lambda ids: [u for u in units if u.id in ids]
    store.get.side_effect = lambda uid: next((u for u in units if u.id == uid), None)
    return MemoryRetriever(store=store)


def test_persona_clusters_rejects_same_day_only():
    units = [
        _unit("a", "项目延期", days_ago=1.0),
        _unit("b", "项目延期讨论", days_ago=1.0),
    ]
    r = _retriever(units)
    assert r.persona_clusters(min_span_days=2.0, min_recurrence=2) == []


def test_persona_clusters_accepts_cross_day_recurring_theme():
    units = [
        _unit(
            "a",
            "项目延期：初次",
            days_ago=10.0,
            tier=MemoryTier.long,
            recall_count=2,
            rehearsal_count=1,
        ),
        _unit(
            "b",
            "项目延期：复盘",
            days_ago=3.0,
            recall_count=1,
            rehearsal_count=2,
            narrative_ref_count=1,
        ),
    ]
    r = _retriever(units)
    clusters = r.persona_clusters(
        min_span_days=2.0,
        min_recurrence=2,
        min_mass=0.5,
        min_persona_score=0.1,
    )
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.recurrence >= 2
    assert cluster.span_days >= 2.0
    assert len(cluster.unit_ids) == 2
    assert cluster.cluster_key


def test_to_buffer_meta_carries_fetch_anchors():
    unit = _unit("u1", "协作犹豫", days_ago=5.0, rehearsal_count=2)
    cluster = PersonaThemeCluster(
        theme="协作犹豫",
        mass=3.2,
        units=[ScoredUnit(unit, relevance=1.0, activation=0.7)],
        cluster_key="abc123",
        profile=PersonaThemeProfile(
            recurrence=2,
            span_days=5.0,
            cohesion=0.8,
            persona_score=0.6,
            long_term_ratio=0.5,
        ),
    )
    meta = cluster.to_buffer_meta(tick_id="tick-9")
    assert meta["theme"] == "协作犹豫"
    assert meta["tick_id"] == "tick-9"
    assert meta["unit_ids"] == ["u1"]
    assert meta["cluster_key"] == "abc123"
    assert meta["recurrence"] == 2
    assert meta["span_days"] == 5.0


def test_fetch_persona_cluster_uses_anchor_and_theme():
    units = [
        _unit("a", "失败反刍", days_ago=8.0, rehearsal_count=3),
        _unit("b", "失败反刍复盘", days_ago=2.0, recall_count=2),
        _unit("c", "无关主题", days_ago=1.0),
    ]
    r = _retriever(units)
    material = r.fetch_persona_cluster(
        "失败反刍",
        unit_ids=["a"],
        top_k=5,
        similarity_threshold=0.0,
    )
    ids = material.unit_ids
    assert "a" in ids
    assert "c" not in ids
    payload = material.to_dict()
    assert payload["theme"] == "失败反刍"
    assert payload["lines"]
    assert payload["units"]


def test_cluster_signal_roundtrip_extended_meta():
    payload = {
        "theme": "模式A",
        "tick_id": "t1",
        "cluster_key": "key1",
        "unit_ids": ["u1", "u2"],
        "mass": 2.5,
        "span_days": 4.0,
        "recurrence": 2,
        "persona_score": 0.55,
    }
    signal = ClusterSignal.from_cluster_meta(payload)
    assert signal.unit_ids == ["u1", "u2"]
    assert signal.mass == 2.5
    assert signal.recurrence == 2
    restored = ClusterSignal.from_dict(signal.to_dict())
    assert restored.unit_ids == ["u1", "u2"]
    assert restored.cluster_key == "key1"


class _MemoryPortStub:
    def list_drift_units(self, *, month, anchor_unit_ids=None, limit=120):
        return []


def test_monthly_drift_requires_drift_units():
    from agent.soul.persona.buffer import ExperienceBuffer
    from agent.soul.persona.buffer.store import BufferMeta
    from agent.soul.persona.self_concept.concept import SelfConcept

    buffer = ExperienceBuffer(
        [
            ClusterSignal.from_cluster_meta(
                {
                    "theme": "模式A",
                    "unit_ids": ["u1"],
                    "cluster_key": "k1",
                }
            )
        ]
    )
    meta = BufferMeta()
    concept = SelfConcept()

    result = MonthlyDriftUpdater().run(
        buffer=buffer,
        meta=meta,
        concept=concept,
        profile=__import__(
            "agent.soul.persona.profile.profile", fromlist=["PersonaProfile"]
        ).PersonaProfile(name="test"),
        memory_port=_MemoryPortStub(),
        force=True,
    )
    assert result.ok is True
    assert result.applied is False
    assert result.reason == "no_drift_units"
