"""R2 成长快照：以 store 实际状态为准的时点画像（防事件流水漂移）。

快照在 sleep 流程末尾落盘（``SleepService.run`` 经 build.py 注入的 hook 调用），
字段覆盖 PRD 2.1 五维度（G1 规模 / G2 结构 / G3 强度 / G5 遗忘面）与
P5 要求的向量基建形态标记。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.soul.memory.graph.node_store import GraphNodeStore
    from agent.soul.memory.ports import GraphEdgeStore


def _quantile(sorted_values: list[int | float], q: float) -> float:
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, max(0, int(round(q * (len(sorted_values) - 1)))))
    return float(sorted_values[idx])


def _counter_profile(values: list[int]) -> dict:
    if not values:
        return {"count": 0, "zero_share": 0.0, "multi_share": 0.0, "p50": 0, "p90": 0, "max": 0}
    ordered = sorted(values)
    n = len(values)
    return {
        "count": n,
        "zero_share": round(sum(1 for v in values if v == 0) / n, 4),
        "multi_share": round(sum(1 for v in values if v >= 2) / n, 4),
        "p50": int(_quantile(ordered, 0.50)),
        "p90": int(_quantile(ordered, 0.90)),
        "max": int(ordered[-1]),
    }


def _enum_value(value) -> str:
    """enum/str 统一取末段（MemoryNetwork.event → event；已是 event 则原样）。"""
    raw = getattr(value, "value", value)
    text = str(raw or "")
    return text.rsplit(".", 1)[-1]


def build_growth_snapshot(
    nodes: GraphNodeStore,
    edges: GraphEdgeStore | None,
    *,
    vector_infra_enabled: bool = False,
    limit: int = 100_000,
) -> dict:
    all_nodes = nodes.list_all(limit=limit)
    all_edges: list = []
    if edges is not None and hasattr(edges, "list_all"):
        all_edges = edges.list_all(limit=limit)

    nodes_by_network_type: dict[str, int] = {}
    nodes_by_tier: dict[str, int] = {}
    for node in all_nodes:
        network = _enum_value(getattr(node, "network", None))
        node_type = _enum_value(getattr(node, "MEMORY_TYPE", ""))
        key = f"{network}/{node_type}" if network else node_type
        nodes_by_network_type[key] = nodes_by_network_type.get(key, 0) + 1
        tier = _enum_value(getattr(node, "tier", None))
        nodes_by_tier[tier] = nodes_by_tier.get(tier, 0) + 1

    edges_by_type: dict[str, int] = {}
    degree: dict[str, int] = {}
    for edge in all_edges:
        edge_type = _enum_value(getattr(edge, "edge_type", None))
        edges_by_type[edge_type] = edges_by_type.get(edge_type, 0) + 1
        degree[str(edge.from_id)] = degree.get(str(edge.from_id), 0) + 1
        degree[str(edge.to_id)] = degree.get(str(edge.to_id), 0) + 1

    node_ids = {str(n.id) for n in all_nodes}
    linked = {nid for nid in degree if nid in node_ids}
    n_nodes = len(all_nodes)
    n_edges = len(all_edges)
    orphan_rate = round(1.0 - (len(linked) / n_nodes), 4) if n_nodes else 0.0

    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "growth_snapshot",
        "vector_infra_enabled": bool(vector_infra_enabled),
        "node_count": n_nodes,
        "edge_count": n_edges,
        "nodes_by_network_type": nodes_by_network_type,
        "nodes_by_tier": nodes_by_tier,
        "edges_by_type": edges_by_type,
        # G1/G2 核心斜率指标
        "edge_node_ratio": round(n_edges / n_nodes, 4) if n_nodes else 0.0,
        "avg_degree": round(sum(degree.values()) / n_nodes, 4) if n_nodes else 0.0,
        "orphan_rate": orphan_rate,
        # G3 强度分布
        "recall_count_profile": _counter_profile([int(getattr(n, "recall_count", 0) or 0) for n in all_nodes]),
        "rehearsal_count_profile": _counter_profile([int(getattr(n, "rehearsal_count", 0) or 0) for n in all_nodes]),
        "narrative_ref_profile": _counter_profile([int(getattr(n, "narrative_ref_count", 0) or 0) for n in all_nodes]),
    }
