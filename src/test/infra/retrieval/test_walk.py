from __future__ import annotations

from infra.retrieval.walk import SemanticBeamWalker


def _walker(edges, vecs, **kw):
    return SemanticBeamWalker(
        lambda n: edges.get(n, []), lambda n: vecs.get(n), **kw
    )


def test_walks_toward_semantically_similar_direction():
    # a 的邻居 b(语义近) 与 c(语义远)；b 的邻居 d(语义更近)
    edges = {"a": [("b", 0.5), ("c", 0.9)], "b": [("d", 0.5)], "c": [("e", 0.9)], "d": [], "e": []}
    vecs = {"a": [1, 0], "b": [0.9, 0.1], "c": [0.1, 0.9], "d": [0.95, 0.05], "e": [0.1, 0.95]}
    hits = _walker(edges, vecs, beam_width=2, max_nodes=5).walk([1.0, 0.0], {"a": 1.0})
    ids = [h.node_id for h in hits]
    assert "a" in ids and "b" in ids and "d" in ids
    assert hits[0].node_id in ("d", "a")  # 语义方向的 d 或种子 a 居首
    assert all(h.hop >= 0 for h in hits)


def test_max_nodes_budget_respected():
    edges = {
        "s": [(f"n{i}", 0.9) for i in range(20)],
        **{f"n{i}": [] for i in range(20)},
    }
    vecs = {**{"s": [1.0, 0.0]}, **{f"n{i}": [1.0, 0.0] for i in range(20)}}
    hits = _walker(edges, vecs, beam_width=3, max_nodes=10).walk([1.0, 0.0], {"s": 1.0})
    assert len(hits) <= 10


def test_no_revisit_and_deterministic():
    edges = {
        "a": [("b", 0.9), ("c", 0.8)],
        "b": [("a", 1.0), ("c", 0.9)],
        "c": [("a", 1.0), ("b", 0.9)],
    }
    vecs = {"a": [1, 0], "b": [1, 0], "c": [0, 1]}
    w = _walker(edges, vecs, beam_width=2, max_nodes=10)
    h1 = w.walk([1.0, 0.0], {"a": 1.0})
    h2 = w.walk([1.0, 0.0], {"a": 1.0})
    assert h1 == h2
    ids = [h.node_id for h in h1]
    assert len(ids) == len(set(ids))


def test_empty_seeds_returns_empty():
    hits = _walker({}, {}).walk([1.0], {})
    assert hits == []


def test_without_query_vector_walks_by_edge_weight():
    edges = {"a": [("b", 0.9)], "b": []}
    vecs = {"a": [1, 0], "b": [1, 0]}
    hits = _walker(edges, vecs, max_nodes=5).walk([], {"a": 1.0})
    # 无语义项时累计分 = 种子分 + 边权：b(1.9w) > a(1.0)
    assert [h.node_id for h in hits] == ["b", "a"]
    assert hits[1].hop == 0 and hits[0].hop == 1


def test_min_step_score_prunes_weak_candidates():
    edges = {"a": [("b", 0.05)], "b": []}
    vecs = {"a": [0, 1], "b": [0, 1]}  # 与查询[1,0]余弦=0
    hits = _walker(
        edges, vecs, max_nodes=5, w_edge=0.0, w_semantic=1.0, min_step_score=0.5
    ).walk([1.0, 0.0], {"a": 1.0})
    assert [h.node_id for h in hits] == ["a"]  # b 的步分 0 < 0.5 被剪


def test_seed_scores_seed_collected_with_their_score():
    edges = {"x": [], "y": []}
    vecs = {"x": [1, 0], "y": [1, 0]}
    hits = _walker(edges, vecs, beam_width=2, max_nodes=5).walk([1.0, 0.0], {"x": 0.9, "y": 0.5})
    by_id = {h.node_id: h for h in hits}
    assert by_id["x"].hop == 0 and by_id["x"].score == 0.9
    assert by_id["y"].hop == 0 and by_id["y"].score == 0.5
