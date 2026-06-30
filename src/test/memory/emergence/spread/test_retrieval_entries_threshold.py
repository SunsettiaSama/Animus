from __future__ import annotations

from agent.soul.memory.domain import ActivationCue, EdgeType, MemoryEdge
from agent.soul.memory.graph.cluster import ClusterIndex
from agent.soul.memory.graph.networks.event.node import FactualMemory
from agent.soul.memory.graph.scored import ScoredUnit
from agent.soul.memory.emergence.spread.service import SpreadActivationService


class _NodeStore:
    def __init__(self, nodes: list[FactualMemory]) -> None:
        self._nodes = {node.id: node for node in nodes}

    def get(self, node_id: str):
        return self._nodes.get(node_id)

    def get_many(self, node_ids: list[str]):
        return [self._nodes[node_id] for node_id in node_ids if node_id in self._nodes]

    def list_by_network(self, network, *, limit: int = 50):
        return [node for node in self._nodes.values() if node.network == network][:limit]


class _EdgeStore:
    def __init__(self, edges: list[MemoryEdge] | None = None) -> None:
        self._edges = list(edges or [])

    def put(self, edge: MemoryEdge) -> None:
        self._edges.append(edge)

    def out_edges(self, node_id: str, edge_type: EdgeType | None = None):
        out = [edge for edge in self._edges if edge.from_id == node_id]
        if edge_type is not None:
            out = [edge for edge in out if edge.edge_type == edge_type]
        return out

    def in_edges(self, node_id: str, edge_type: EdgeType | None = None):
        incoming = [edge for edge in self._edges if edge.to_id == node_id]
        if edge_type is not None:
            incoming = [edge for edge in incoming if edge.edge_type == edge_type]
        return incoming

    def delete_edge(self, edge_id: str) -> None:
        self._edges = [edge for edge in self._edges if edge.id != edge_id]

    def delete_by_node(self, node_id: str) -> None:
        self._edges = [
            edge for edge in self._edges
            if edge.from_id != node_id and edge.to_id != node_id
        ]


class _Query:
    def __init__(self, scored: list[ScoredUnit]) -> None:
        self._scored = scored

    def hybrid(self, *args, **kwargs):
        top_k = int(kwargs.get("top_k", 5))
        return list(self._scored[:top_k])

    def hybrid_with_vector(self, *args, **kwargs):
        return []

    def wander(self, *args, **kwargs):
        return []


def _node(node_id: str, text: str) -> FactualMemory:
    return FactualMemory(
        id=node_id,
        focus=text,
        fact=text,
        base_activation=0.5,
    )


def _service(nodes: list[FactualMemory], query: _Query, edges: list[MemoryEdge] | None = None):
    return SpreadActivationService(
        _NodeStore(nodes),
        _EdgeStore(edges),
        vectors=None,
        query=query,
        cluster_index=ClusterIndex(),
        threshold=0.2,
        max_hops=2,
        hop_decay=0.5,
        point_top_k=5,
    )


def test_retrieval_sub_entries_keep_spread_and_hybrid_separate():
    seed = _node("seed", "blueberry cat memory")
    neighbor = _node("neighbor", "promotion checklist memory")
    service = _service(
        [seed, neighbor],
        _Query([]),
        edges=[
            MemoryEdge(
                from_id=seed.id,
                to_id=neighbor.id,
                edge_type=EdgeType.related_to,
                weight=1.0,
            )
        ],
    )
    cue = ActivationCue(session_id="s", interactor_id="", user_text="blueberry")

    spread = service.query_spread_sync(cue)
    hybrid = service.query_hybrid_sync(cue)

    assert seed.id in spread.unit_ids
    assert neighbor.id in spread.unit_ids
    assert hybrid.precise_unit_ids == []


def test_precise_threshold_minus_one_keeps_existing_hybrid_behavior():
    weak = _node("weak", "weak candidate")
    strong = _node("strong", "strong candidate")
    service = _service(
        [weak, strong],
        _Query([
            ScoredUnit(weak, relevance=0.12, activation=0.9, final_score=0.43),
            ScoredUnit(strong, relevance=0.71, activation=0.4, final_score=0.59),
        ]),
    )
    result = service.query_hybrid_sync(
        ActivationCue(session_id="s", interactor_id="", user_text="anything"),
        precise_relevance_threshold=-1,
    )

    assert result.precise_unit_ids == [weak.id, strong.id]


def test_precise_threshold_filters_by_relevance_not_final_score():
    weak_fresh = _node("weak-fresh", "fresh but unrelated")
    borderline = _node("borderline", "borderline related")
    strong = _node("strong", "strongly related")
    service = _service(
        [weak_fresh, borderline, strong],
        _Query([
            ScoredUnit(weak_fresh, relevance=0.20, activation=1.0, final_score=0.52),
            ScoredUnit(borderline, relevance=0.40, activation=0.3, final_score=0.36),
            ScoredUnit(strong, relevance=0.68, activation=0.3, final_score=0.53),
        ]),
    )
    result = service.query_hybrid_sync(
        ActivationCue(session_id="s", interactor_id="", user_text="anything"),
        precise_relevance_threshold=0.40,
    )

    assert result.precise_unit_ids == [borderline.id, strong.id]


def test_precise_threshold_benchmark_sweep_marks_miss_when_too_strict():
    weak = _node("weak", "weak")
    borderline = _node("borderline", "borderline")
    strong = _node("strong", "strong")
    service = _service(
        [weak, borderline, strong],
        _Query([
            ScoredUnit(weak, relevance=0.20, activation=0.5, final_score=0.32),
            ScoredUnit(borderline, relevance=0.40, activation=0.5, final_score=0.44),
            ScoredUnit(strong, relevance=0.62, activation=0.5, final_score=0.57),
        ]),
    )
    cue = ActivationCue(session_id="s", interactor_id="", user_text="anything")

    sweep = {
        threshold: service.query_hybrid_sync(
            cue,
            precise_relevance_threshold=threshold,
        ).precise_unit_ids
        for threshold in (-1.0, 0.40, 0.63)
    }

    assert sweep[-1.0] == [weak.id, borderline.id, strong.id]
    assert sweep[0.40] == [borderline.id, strong.id]
    assert sweep[0.63] == []
