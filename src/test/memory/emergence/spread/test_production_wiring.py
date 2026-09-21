from __future__ import annotations

from types import SimpleNamespace

from agent.soul.memory.domain import ActivationCue, EdgeType, MemoryEdge
from agent.soul.memory.graph.cluster import ClusterIndex
from agent.soul.memory.graph.networks.event.node import FactualMemory
from agent.soul.memory.graph.scored import ScoredUnit
from agent.soul.memory.emergence.spread.service import SpreadActivationService
from infra.retrieval import TemplateRewriter


class _NodeStore:
    def __init__(self, nodes):
        self._nodes = {n.id: n for n in nodes}

    def get(self, node_id):
        return self._nodes.get(node_id)

    def get_many(self, node_ids):
        return [self._nodes[i] for i in node_ids if i in self._nodes]

    def list_by_network(self, network, *, limit: int = 50):
        return [n for n in self._nodes.values() if n.network == network][:limit]


class _EdgeStore:
    def __init__(self, edges=None):
        self._edges = list(edges or [])

    def out_edges(self, node_id, edge_type=None):
        return [e for e in self._edges if e.from_id == node_id]


class _Query:
    """记录 hybrid 收到的 query 文本，返回预置 scored。"""

    def __init__(self, scored=None):
        self._scored = list(scored or [])
        self.hybrid_queries: list[str] = []

    def hybrid(self, text, *args, **kwargs):
        self.hybrid_queries.append(str(text))
        top_k = int(kwargs.get("top_k", 5))
        return list(self._scored[:top_k])

    def hybrid_with_vector(self, *args, **kwargs):
        return []

    def wander(self, *args, **kwargs):
        return []


class _Vectors:
    """embed_query 返回固定向量；iter_entries 暴露节点向量。"""

    def __init__(self, vec_map, query_vector):
        self._vec_map = dict(vec_map)
        self._query_vector = list(query_vector)
        self.iter_entries_called = False

    def embed_query(self, text):
        return list(self._query_vector)

    def iter_entries(self):
        self.iter_entries_called = True
        return [
            SimpleNamespace(node_id=nid, network=None, text="", vector=list(v))
            for nid, v in self._vec_map.items()
        ]


def _node(node_id, text):
    return FactualMemory(id=node_id, focus=text, fact=text, base_activation=0.5)


def _cue(text):
    return ActivationCue(session_id="s", interactor_id="", user_text=text)


def _service(nodes, query, edges=None, vectors=None, **kw):
    return SpreadActivationService(
        _NodeStore(nodes),
        _EdgeStore(edges),
        vectors,
        query,
        ClusterIndex(),
        point_top_k=5,
        **kw,
    )


def test_point_query_uses_rewritten_query_text():
    ramen = _node("ramen", "拉面店")
    query = _Query([ScoredUnit(ramen, relevance=0.9, final_score=0.9)])
    service = _service([ramen], query, query_rewriter=TemplateRewriter())
    result = service.query_hybrid_sync(_cue("你还记得那家拉面店吗"))

    assert query.hybrid_queries, "hybrid 应被调用"
    sent = query.hybrid_queries[0]
    assert "还记得" not in sent
    assert "吗" not in sent
    assert "拉面店" in sent
    assert result.precise_unit_ids == ["ramen"]


def test_no_rewriter_sends_raw_cue_text():
    ramen = _node("ramen", "anything")
    query = _Query([ScoredUnit(ramen, final_score=0.5)])
    service = _service([ramen], query)
    service.query_hybrid_sync(_cue("你还记得那家拉面店吗"))
    assert query.hybrid_queries[0] == "你还记得那家拉面店吗"


def test_beam_walk_appends_graph_neighbor_within_budget():
    seed = _node("seed", "种子节点")
    neighbor = _node("neighbor", "语义近邻")
    far = _node("far", "语义远端")
    edges = [
        MemoryEdge(from_id="seed", to_id="neighbor", edge_type=EdgeType.related_to, weight=0.9),
        MemoryEdge(from_id="seed", to_id="far", edge_type=EdgeType.related_to, weight=0.9),
    ]
    # 查询向量与 neighbor 同向、与 far 正交
    vectors = _Vectors(
        {"seed": [1.0, 0.0], "neighbor": [0.95, 0.05], "far": [0.0, 1.0]},
        query_vector=[1.0, 0.0],
    )
    query = _Query([ScoredUnit(seed, relevance=0.9, final_score=0.9)])
    service = _service(
        [seed, neighbor, far],
        query,
        edges=edges,
        vectors=vectors,
        query_rewriter=TemplateRewriter(),
        beam_walk_enabled=True,
        beam_walk_width=2,
        beam_walk_max_nodes=4,
    )
    result = service.query_hybrid_sync(_cue("那家拉面店"))

    assert "seed" in result.precise_unit_ids
    assert "neighbor" in result.precise_unit_ids  # 语义方向邻居被束搜索带入
    # 预算内远端也可能进入，但必须排在语义近邻之后（束搜索的排序语义）
    if "far" in result.precise_unit_ids:
        assert result.precise_unit_ids.index("neighbor") < result.precise_unit_ids.index("far")
        assert result.precise_unit_ids[-1] != "seed"
    assert vectors.iter_entries_called


def test_beam_walk_disabled_keeps_legacy_precise():
    seed = _node("seed", "种子")
    neighbor = _node("neighbor", "近邻")
    edges = [
        MemoryEdge(from_id="seed", to_id="neighbor", edge_type=EdgeType.related_to, weight=0.9),
    ]
    vectors = _Vectors({"seed": [1.0, 0.0], "neighbor": [1.0, 0.0]}, query_vector=[1.0, 0.0])
    query = _Query([ScoredUnit(seed, relevance=0.9, final_score=0.9)])
    service = _service(
        [seed, neighbor], query, edges=edges, vectors=vectors, beam_walk_enabled=False
    )
    result = service.query_hybrid_sync(_cue("那家拉面店"))
    assert result.precise_unit_ids == ["seed"]


def test_rewriter_failure_falls_back_to_raw_text():
    class _Boom:
        def rewrite(self, text, *, intent="recall"):
            raise RuntimeError("boom")

    ramen = _node("ramen", "x")
    query = _Query([ScoredUnit(ramen, final_score=0.5)])
    service = _service([ramen], query, query_rewriter=_Boom())
    result = service.query_hybrid_sync(_cue("你还记得那家拉面店吗"))
    assert query.hybrid_queries[0] == "你还记得那家拉面店吗"
    assert result.precise_unit_ids == ["ramen"]
