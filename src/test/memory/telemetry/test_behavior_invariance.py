"""R5.1 行为不变锁：telemetry 全开/全关，检索结果逐位一致（PRD 2.4）。"""
from __future__ import annotations

from random import Random
from types import SimpleNamespace

from agent.soul.memory.domain import ActivationCue, EdgeType, MemoryEdge
from agent.soul.memory.graph.cluster import ClusterIndex
from agent.soul.memory.graph.networks.event.node import FactualMemory
from agent.soul.memory.graph.scored import ScoredUnit
from agent.soul.memory.emergence.spread.service import SpreadActivationService
from agent.soul.speak.responders.request_driven.composer.domain.retrieve import (
    MemoryRetrievePolicy,
)
from agent.soul.speak.responders.request_driven.composer.domain.staging import (
    MemoryStagingBuffer,
)
from agent.soul.speak.responders.request_driven.composer.ports.memory import MemoryUnit
from agent.soul.memory.telemetry import (
    MemoryTelemetryConfig,
    configure_memory_telemetry,
    reset_memory_telemetry,
)
from infra.retrieval import TemplateRewriter

from .conftest import read_events


class _NodeStore:
    def __init__(self, nodes):
        self._nodes = {n.id: n for n in nodes}

    def get(self, node_id):
        return self._nodes.get(node_id)

    def get_many(self, node_ids):
        return [self._nodes[i] for i in node_ids if i in self._nodes]


class _EdgeStore:
    def __init__(self, edges):
        self._edges = list(edges)

    def out_edges(self, node_id, edge_type=None):
        return [e for e in self._edges if e.from_id == node_id]


class _Query:
    def __init__(self, scored):
        self._scored = list(scored)

    def hybrid(self, text, *args, **kwargs):
        return list(self._scored[: int(kwargs.get("top_k", 5))])

    def hybrid_with_vector(self, *args, **kwargs):
        return []

    def wander(self, *args, **kwargs):
        return []


class _Vectors:
    def __init__(self, vec_map, query_vector):
        self._vec_map = dict(vec_map)
        self._query_vector = list(query_vector)

    def embed_query(self, text):
        return list(self._query_vector)

    def iter_entries(self):
        return [
            SimpleNamespace(node_id=nid, network=None, text="", vector=list(v))
            for nid, v in self._vec_map.items()
        ]


def _build_service():
    seed = FactualMemory(id="seed", focus="种子", fact="种子事实", base_activation=0.5)
    neighbor = FactualMemory(id="neighbor", focus="近邻", fact="近邻事实", base_activation=0.5)
    edges = [
        MemoryEdge(from_id="seed", to_id="neighbor", edge_type=EdgeType.related_to, weight=0.9),
    ]
    vectors = _Vectors(
        {"seed": [1.0, 0.0], "neighbor": [0.95, 0.05]}, query_vector=[1.0, 0.0]
    )
    query = _Query([ScoredUnit(seed, relevance=0.9, final_score=0.9)])
    return SpreadActivationService(
        _NodeStore([seed, neighbor]),
        _EdgeStore(edges),
        vectors,
        query,
        ClusterIndex(),
        point_top_k=5,
        query_rewriter=TemplateRewriter(),
        beam_walk_enabled=True,
        beam_walk_width=2,
        beam_walk_max_nodes=4,
    )


def _point_query_signature():
    result = _build_service().query_hybrid_sync(
        ActivationCue(session_id="s", interactor_id="", user_text="你还记得那家拉面店吗")
    )
    return (
        list(result.precise_unit_ids),
        list(result.associative_unit_ids),
        list(result.precise_lines),
        list(result.associative_lines),
    )


def _compose_signature():
    staging = MemoryStagingBuffer(rng=Random(7))
    policy = MemoryRetrievePolicy(staging, rng=Random(42), query_rewriter=TemplateRewriter())
    staging.ingest_units(
        "sess",
        [MemoryUnit(unit_id=f"u{i}", text=f"关于话题{i}的记忆内容") for i in range(3)],
        kind="event",
    )
    hits = policy.retrieve("sess", primary_query="还记得话题1吗", mode="hybrid")
    return tuple((h.unit.unit_id, round(h.score, 6), h.mode) for h in hits)


def test_point_query_identical_off_vs_on(tmp_path):
    try:
        configure_memory_telemetry(
            MemoryTelemetryConfig(enabled=False, dir=str(tmp_path / "off"))
        )
        baseline = _point_query_signature()
        assert baseline and baseline[0], "基线非空（rewriter+束搜索应生效）"

        configure_memory_telemetry(
            MemoryTelemetryConfig(enabled=True, dir=str(tmp_path / "on"))
        )
        instrumented = _point_query_signature()
        assert instrumented == baseline, "telemetry 开启不得改变点查询结果（逐位一致）"
    finally:
        reset_memory_telemetry()


def test_compose_retrieve_identical_off_vs_on(tmp_path):
    try:
        configure_memory_telemetry(
            MemoryTelemetryConfig(enabled=False, dir=str(tmp_path / "off"))
        )
        baseline = _compose_signature()
        assert baseline, "基线非空"

        configure_memory_telemetry(
            MemoryTelemetryConfig(enabled=True, dir=str(tmp_path / "on"))
        )
        instrumented = _compose_signature()
        assert instrumented == baseline, "埋点不得改变 compose 检索结果"
    finally:
        reset_memory_telemetry()


def test_point_query_emits_entry_b_event(telemetry):
    result = _build_service().query_hybrid_sync(
        ActivationCue(session_id="s", interactor_id="i1", user_text="你还记得那家拉面店吗")
    )
    assert result.precise_unit_ids
    b_events = [
        e for e in read_events(telemetry)
        if e.get("event") == "retrieval_performed" and e.get("entry") == "B_point_query"
    ]
    assert len(b_events) == 1
    e = b_events[0]
    assert e["session_id"] == "s"
    assert e["result_count"] == len(result.merged_unit_ids())
    assert e["results"], "结果明细（id 列表）必须入事件（F7 依赖）"
    assert "拉面店" in e["rewritten_query"]
    assert e["template_id"]
    assert e["elapsed_ms"] >= 0


def test_compose_retrieve_emits_entry_c_event(telemetry):
    signature = _compose_signature()
    assert signature
    c_events = [
        e for e in read_events(telemetry)
        if e.get("event") == "retrieval_performed" and e.get("entry") == "C_compose"
    ]
    assert c_events, "入口 C 应发 retrieval_performed"
    assert c_events[-1]["branch"] == "normal"
    assert c_events[-1]["result_count"] == len(signature)
