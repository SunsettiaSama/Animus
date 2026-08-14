from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from typing import TypeAlias

from .types import NodeStatus

# (node_id, depends_on_subset_of_known_ids, status)
DagNodeSpec: TypeAlias = tuple[str, frozenset[str], NodeStatus]


def edges_from_specs(specs: Sequence[tuple[str, frozenset[str]]]) -> dict[str, frozenset[str]]:
    return {nid: deps for nid, deps in specs}


def validate_known_dependencies(node_ids: Set[str], deps: Mapping[str, frozenset[str]]) -> None:
    unknown: list[str] = []
    for nid, ds in deps.items():
        if nid not in node_ids:
            unknown.append(f"node {nid!r} not in graph")
        for d in ds:
            if d not in node_ids:
                unknown.append(f"{nid!r} depends on unknown id {d!r}")
    if unknown:
        raise ValueError("invalid DAG specification: " + "; ".join(unknown))


def has_cycle(node_ids: Set[str], deps: Mapping[str, frozenset[str]]) -> bool:
    """Return True if the dependency graph contains a directed cycle (Kahn-style detect)."""
    validate_known_dependencies(node_ids, deps)
    in_degree: dict[str, int] = {n: 0 for n in node_ids}
    children: dict[str, list[str]] = {n: [] for n in node_ids}
    for nid in node_ids:
        for d in deps.get(nid, frozenset()):
            in_degree[nid] += 1
            children[d].append(nid)
    queue = [n for n, deg in in_degree.items() if deg == 0]
    visited = 0
    while queue:
        u = queue.pop()
        visited += 1
        for v in children[u]:
            in_degree[v] -= 1
            if in_degree[v] == 0:
                queue.append(v)
    return visited != len(node_ids)


def finished_for_dependencies(status: NodeStatus) -> bool:
    return status in (NodeStatus.done, NodeStatus.skipped)


def ready_node_ids(nodes: Sequence[DagNodeSpec]) -> list[str]:
    """Nodes that are pending and whose dependencies are all done or skipped."""
    by_id = {nid: (deps, st) for nid, deps, st in nodes}
    done_ids = {nid for nid, (_, st) in by_id.items() if finished_for_dependencies(st)}
    ready = [
        nid
        for nid, (deps, st) in by_id.items()
        if st == NodeStatus.pending and deps <= done_ids
    ]
    return sorted(ready)


def max_parallel_width(node_ids: Set[str], deps: Mapping[str, frozenset[str]]) -> int:
    """
    Topological layering via Kahn; returns the maximum width of any wave.
    Edges point from dependency to dependent (dep must finish before nid runs).
    Unknown dependency ids are ignored (same rule as PlanDocument.compute_dag_width).
    """
    if not node_ids:
        return 1
    in_degree: dict[str, int] = {n: 0 for n in node_ids}
    children: dict[str, list[str]] = {n: [] for n in node_ids}
    for nid in node_ids:
        for dep in deps.get(nid, frozenset()):
            if dep in node_ids:
                in_degree[nid] += 1
                children[dep].append(nid)
    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    max_width = max(len(queue), 1)
    while queue:
        next_wave: list[str] = []
        for tid in queue:
            for child in children[tid]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    next_wave.append(child)
        if next_wave:
            max_width = max(max_width, len(next_wave))
        queue = next_wave
    return max_width


def topological_layers(node_ids: Set[str], deps: Mapping[str, frozenset[str]]) -> list[list[str]]:
    """Return layers of node ids; layer i only depends on layers j < i."""
    if not node_ids:
        return []
    in_degree: dict[str, int] = {n: 0 for n in node_ids}
    children: dict[str, list[str]] = {n: [] for n in node_ids}
    for nid in node_ids:
        for dep in deps.get(nid, frozenset()):
            if dep in node_ids:
                in_degree[nid] += 1
                children[dep].append(nid)
    wave = [tid for tid, deg in in_degree.items() if deg == 0]
    layers: list[list[str]] = []
    while wave:
        layers.append(sorted(wave))
        next_wave: list[str] = []
        for tid in wave:
            for child in children[tid]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    next_wave.append(child)
        wave = sorted(next_wave)
    return layers
