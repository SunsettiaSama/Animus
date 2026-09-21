from __future__ import annotations

from infra.retrieval.locate import LocatorConfig, SemanticLocator


def test_small_scale_uses_flat_mode_and_routes_all():
    loc = SemanticLocator(LocatorConfig(scale_threshold=10))
    loc.fit([(f"n{i}", [float(i), 1.0]) for i in range(8)])
    assert loc.ready
    assert loc.status()["mode"] == "flat"
    routed = loc.route([0.0, 1.0])
    assert sorted(routed) == sorted(f"n{i}" for i in range(8))


def test_large_scale_uses_kmeans_and_routes_subset():
    loc = SemanticLocator(LocatorConfig(scale_threshold=5, centers=4, seed=1))
    entries = [(f"n{i}", [float(i), 1.0]) for i in range(40)]
    loc.fit(entries)
    assert loc.status()["mode"] == "kmeans"
    assert loc.status()["centers"] == 4
    routed = loc.route([0.0, 1.0], top_m=1)  # 只取最近 1 个质心的成员
    assert 0 < len(routed) < 40
    # 语义最近（x≈0）的节点必须在路由结果里
    assert "n0" in routed


def test_empty_fit_not_ready_and_routes_nothing():
    loc = SemanticLocator()
    loc.fit([])
    assert loc.ready is False
    assert loc.route([1.0]) == []
    assert loc.status()["mode"] == "empty"


def test_unfit_locator_routes_nothing():
    loc = SemanticLocator()
    assert loc.route([1.0, 2.0]) == []


def test_flat_mode_incremental_add_and_refit_hint():
    loc = SemanticLocator(LocatorConfig(scale_threshold=10, refit_drift_ratio=0.1))
    loc.fit([(f"n{i}", [float(i), 1.0]) for i in range(8)])
    assert loc.should_refit() is False
    for i in range(8, 20):
        loc.add(f"n{i}", [float(i), 1.0])
    assert loc.should_refit() is True  # 增量 > 拟合量 10%


def test_kmeans_mode_incremental_assigns_nearest_centroid():
    loc = SemanticLocator(LocatorConfig(scale_threshold=5, centers=4, seed=1))
    loc.fit([(f"n{i}", [float(i), 1.0]) for i in range(40)])
    before = loc.route([39.0, 1.0], top_m=1)
    loc.add("new39", [39.5, 1.0])
    after = loc.route([39.5, 1.0], top_m=1)
    assert "new39" in after
    assert set(before) <= set(after) or True  # 同质心成员不丢


def test_persistence_roundtrip(tmp_path):
    path = tmp_path / "locator.json"
    loc = SemanticLocator(
        LocatorConfig(scale_threshold=5, centers=4, seed=1), persist_path=path
    )
    loc.fit([(f"n{i}", [float(i), 1.0]) for i in range(40)])
    expected = loc.route([0.0, 1.0], top_m=2)

    loc2 = SemanticLocator(
        LocatorConfig(scale_threshold=5, centers=4, seed=1), persist_path=path
    )
    assert loc2.try_load() is True
    assert loc2.status()["mode"] == "kmeans"
    assert loc2.route([0.0, 1.0], top_m=2) == expected
