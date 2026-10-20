"""R5.4 漏斗一致性：报表重放计数 == 事件语义计数；合成漏斗数字逐项核对。"""
from __future__ import annotations

import json

from agent.soul.memory.telemetry.report import (
    build_growth_report,
    load_events,
    load_snapshots,
    render_report_md,
)


def _e(event: str, idx: int, **fields) -> dict:
    e = {"ts": f"2026-09-2{idx % 10}T00:00:00", "event": event}
    e.update(fields)
    return e


def _synthetic_events() -> list[dict]:
    """手工构造一条完整漏斗：10 单元 → 4 标注 → 4 提交(1 被滤) → 3 入图 → 2 建边 → 2 recall。"""
    events: list[dict] = []
    for i in range(10):
        events.append(_e("unit_created", i, unit_id=f"u{i}", source="dialogue", session_id="sess-a" if i < 5 else "sess-b"))
    for i in range(10):
        events.append(_e("unit_annotated", i, unit_id=f"u{i}", annotation_decided=(i < 4), promote_to_memory=(i < 4), outcome="submitted" if i < 4 else "not_promoted"))
    for i in range(4):
        events.append(_e("promote_submitted", i, unit_id=f"u{i}", allowed=(i != 3), node_ids=[f"n{i}"] if i != 3 else [], node_count=0 if i == 3 else 1))
    # u3 被滤 → 只有 u0/u1/u2 产节点；u0 自立、u1/u2 选父
    for i in range(3):
        events.append(_e("node_created", i, node_id=f"n{i}", network="event", node_type="factual", tier="short_term", life_event_id=f"u{i}"))
    events.append(_e("edge_added", 1, edge_type="related_to", from_id="parent0", to_id="n1"))
    events.append(_e("edge_added", 2, edge_type="related_to", from_id="parent0", to_id="n2"))
    # recall：n0/n1 在本会话被想起；n1 在另一会话（sess-b）被检索命中 → F7
    events.append(_e("recall_recorded", 3, node_id="n0"))
    events.append(_e("recall_recorded", 4, node_id="n1"))
    events.append(_e("retrieval_performed", 5, entry="B_point_query", session_id="sess-a", results=[{"id": "n0", "score": 0.8}, {"id": "n1", "score": 0.6}]))
    events.append(_e("retrieval_performed", 6, entry="B_point_query", session_id="sess-b", results=[{"id": "n1", "score": 0.7}]))
    events.append(_e("retrieval_performed", 7, entry="C_compose", session_id="sess-b", results=[]))
    events.append(_e("adoption", 8, session_id="sess-a", turn_index=1, injected_count=2, injected_ids=["n0", "n1"], spilled_count=0))
    events.append(_e("rumination_rewrite", 9, node_id="n0", node_type="factual", new_edges=1))
    events.append(_e("collapse", 9, participant_ids=["x1", "x2"], collision_unit_id="cx"))
    events.append(_e("node_forgotten", 9, node_ids=["n9"], count=1))
    return events


def test_funnel_counts_match_semantics():
    metrics = build_growth_report(_synthetic_events(), [])
    funnel = metrics["funnel"]
    assert funnel["F1_units_created"] == 10
    assert funnel["F2_annotated_promote"] == 4
    assert funnel["F3_submitted"] == 4
    assert funnel["F3_filter_rejected"] == 1
    assert funnel["F4_nodes_created_from_units"] == 3
    assert funnel["F4_units_ingested"] == 3
    assert funnel["F5_nodes_with_parent_edge"] == 2  # n1/n2 有 related_to 父边（to 端）
    assert funnel["F6_nodes_recalled"] == 2
    assert funnel["F7_cross_session_rehit_nodes"] == 1  # n1 在 sess-b 被再次命中
    assert funnel["conversions"]["F4/F1 入图率"] == 0.3


def test_retrieval_and_growth_metrics():
    metrics = build_growth_report(_synthetic_events(), [])
    retrieval = metrics["retrieval"]
    assert retrieval["H1_retrievals_total"] == 3
    assert retrieval["H1_nonempty_rate"] == round(2 / 3, 4)
    assert retrieval["by_entry"]["B_point_query"]["total"] == 2
    assert retrieval["H2_adopted_rate"] == 1.0
    assert retrieval["H2_avg_injected_per_turn"] == 2.0
    growth = metrics["growth"]
    assert growth["G4_reconstruction"]["rumination_rewrites"] == 1
    assert growth["G4_reconstruction"]["collapses"] == 1
    assert growth["G5_decay"]["forgotten"] == 1


def test_questions_answerable():
    metrics = build_growth_report(_synthetic_events(), [])
    q = metrics["questions"]
    assert q["Q3_use_it_or_lose_it"]["answer"] is True
    assert q["Q4_cross_session_recall"]["answer"] is True
    assert q["Q1_funnel_bottleneck"]["stage"], "瓶颈定位必须非空"
    assert q["Q6_distractor_dose"]["node_count"] == 3 - 1
    assert q["Q7_tier_distribution"]["latest_tier"] is None  # 无快照时 tier 用快照口径


def test_report_md_renders_all_sections():
    md = render_report_md(build_growth_report(_synthetic_events(), []))
    for section in ("擢升漏斗", "成长五维", "命中 H1 / H2 / H4", "设计合理性判定 Q1–Q8"):
        assert section in md
    assert "F4/F1 入图率" in md


def test_flow_events_match_store_counts(tmp_path):
    """R5.4 主体：真实微流（伪造 store）产生的事件 → 报表 F4/F5/F6 == store 直接计数。"""
    from agent.soul.memory.telemetry import MemoryTelemetryConfig, configure_memory_telemetry, reset_memory_telemetry
    from agent.soul.memory.telemetry.store_hooks import TelemetryEdgeStore, TelemetryNodeStore

    class _InnerNodes:
        def __init__(self):
            self.rows = {}

        def put(self, node):
            self.rows[node.id] = node

        def get(self, node_id):
            return self.rows.get(node_id)

        def on_recall(self, node_id):
            if node_id in self.rows:
                self.rows[node_id].recall_count += 1

        def list_all(self, limit=2000, network=None):
            return list(self.rows.values())

    class _InnerEdges:
        def __init__(self):
            self.rows = {}

        def put(self, edge):
            self.rows[edge.id] = edge

        def list_all(self, limit=100_000):
            return list(self.rows.values())

    from agent.soul.memory.domain import EdgeType, MemoryEdge
    from agent.soul.memory.graph.networks.event.node import FactualMemory

    configure_memory_telemetry(
        MemoryTelemetryConfig(enabled=True, dir=str(tmp_path / "telemetry"))
    )
    try:
        nodes = TelemetryNodeStore(_InnerNodes())
        edges = TelemetryEdgeStore(_InnerEdges())
        for i in range(5):
            nodes.put(FactualMemory(id=f"n{i}", focus=f"f{i}", fact=f"fact{i}"))
        edges.put(MemoryEdge(from_id="n0", to_id="n1", edge_type=EdgeType.related_to))
        edges.put(MemoryEdge(from_id="n0", to_id="n2", edge_type=EdgeType.related_to))
        for nid in ("n1", "n2", "n3"):
            nodes.on_recall(nid)

        telemetry = configure_memory_telemetry(
            MemoryTelemetryConfig(enabled=True, dir=str(tmp_path / "telemetry"))
        )
        telemetry.flush(timeout=5.0)
        events = load_events(tmp_path / "telemetry" / "memory_events.jsonl")
        metrics = build_growth_report(events, [])
        funnel = metrics["funnel"]
        assert funnel["_created_nodes_total"] == len(nodes.inner.rows) == 5
        assert funnel["F5_nodes_linked_any"] == 3  # n0/n1/n2 被边触达
        assert funnel["F6_nodes_recalled"] == 3
        # 对账：快照（查 store）与事件重放一致
        from agent.soul.memory.telemetry.snapshot import build_growth_snapshot

        snap = build_growth_snapshot(nodes.inner, edges.inner)
        assert snap["node_count"] == funnel["_created_nodes_total"]
        assert snap["edge_count"] == 2
    finally:
        reset_memory_telemetry()
