"""将 ``ExecutionNodeSpec``（九层节点声明）与 ``graph`` 层算法对齐。

- **静态结构**：L1 ``depends_on`` → ``dict[task_id, frozenset[dep]]``，供 ``has_cycle`` / ``max_parallel_width`` 等使用。
- **运行时调度**：为每个节点补上 ``NodeStatus``，得到 ``list[DagNodeSpec]``，供 ``ready_node_ids`` 使用。

``ExecutionNodeSpec`` 的其它层（L2–L9）不参与 graph 拓朴，由实现层在执行/检验阶段读取。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .components.node_spec import ExecutionNodeSpec, node_specs_to_dag_edges, validate_node_graph_ids
from .graph import (
    DagNodeSpec,
    has_cycle,
    max_parallel_width,
    ready_node_ids,
    topological_layers,
    validate_known_dependencies,
)
from .types import NodeStatus


def dep_map_from_nodes(nodes: Sequence[ExecutionNodeSpec]) -> dict[str, frozenset[str]]:
    """校验 id 与依赖后，返回 graph 使用的 deps 映射。"""
    validate_node_graph_ids(nodes)
    return node_specs_to_dag_edges(nodes)


def node_id_set(nodes: Sequence[ExecutionNodeSpec]) -> set[str]:
    validate_node_graph_ids(nodes)
    return {n.task_id for n in nodes}


def to_dag_specs(
    nodes: Sequence[ExecutionNodeSpec],
    status_by_id: Mapping[str, NodeStatus] | None = None,
) -> list[DagNodeSpec]:
    """为每个 ``ExecutionNodeSpec`` 生成一条 ``DagNodeSpec``（默认可全部为 pending）。"""
    deps_map = dep_map_from_nodes(nodes)
    status_by_id = dict(status_by_id or {})
    out: list[DagNodeSpec] = []
    for nid, deps in deps_map.items():
        st = status_by_id.get(nid, NodeStatus.pending)
        out.append((nid, deps, st))
    return out


def assert_acyclic(nodes: Sequence[ExecutionNodeSpec]) -> None:
    """图中存在环则 ``ValueError``。"""
    m = dep_map_from_nodes(nodes)
    ids = set(m)
    if has_cycle(ids, m):
        raise ValueError("execution node graph contains a directed cycle")


def parallel_width(nodes: Sequence[ExecutionNodeSpec]) -> int:
    """与 ``OrchestratorConfig.parallel_limit==0`` 时按 DAG 宽度估值的语义一致。"""
    m = dep_map_from_nodes(nodes)
    return max_parallel_width(set(m), m)


def layers(nodes: Sequence[ExecutionNodeSpec]) -> list[list[str]]:
    """拓扑分层（每层可并行），id 已排序。"""
    m = dep_map_from_nodes(nodes)
    return topological_layers(set(m), m)


def ready_ids(
    nodes: Sequence[ExecutionNodeSpec],
    status_by_id: Mapping[str, NodeStatus] | None = None,
) -> list[str]:
    """给定各节点当前状态（未出现的一律视为 pending），返回就绪节点 id 列表。"""
    m = dep_map_from_nodes(nodes)
    st = dict(status_by_id or {})
    dag: list[DagNodeSpec] = [(nid, m[nid], st.get(nid, NodeStatus.pending)) for nid in m]
    return ready_node_ids(dag)


def index_nodes(nodes: Sequence[ExecutionNodeSpec]) -> dict[str, ExecutionNodeSpec]:
    """便于调度器 O(1) 按 id 取回完整九层规格。"""
    validate_node_graph_ids(nodes)
    return {n.task_id: n for n in nodes}
