from __future__ import annotations

# ── DAG 图算法 ────────────────────────────────────────────────────────────────
from .graph import (
    DagNodeSpec,
    edges_from_specs,
    finished_for_dependencies,
    has_cycle,
    max_parallel_width,
    ready_node_ids,
    topological_layers,
    validate_known_dependencies,
)

# ── ExecutionNodeSpec → graph 桥接 ────────────────────────────────────────────
from .link import (
    assert_acyclic,
    dep_map_from_nodes,
    index_nodes,
    layers,
    parallel_width,
    ready_ids,
    to_dag_specs,
)

# ── 基础类型 ──────────────────────────────────────────────────────────────────
from .types import NodeStatus

# ── 节点规格（声明式）；详见 components 子包 ──────────────────────────────────
from .components import ExecutionNodeSpec, MetadataLayer

# ── 编排协议层 ────────────────────────────────────────────────────────────────
from .orchestration import (
    # 图与节点管理器
    BaseGraphManager,
    DagGraphManager,
    # 计划说明书
    BasePlanSpec,
    # 规划器
    BasePlanner,
    # 重规划器
    BaseReplanner,
    ReplanDecision,
    # 节点执行器
    BaseNodeExecutor,
    # 事件与结果
    OrchestratorEvent,
    OrchestratorResult,
    # 编排器
    BaseOrchestrator,
)

__all__ = [
    # DAG 图算法
    "DagNodeSpec",
    "edges_from_specs",
    "finished_for_dependencies",
    "has_cycle",
    "max_parallel_width",
    "ready_node_ids",
    "topological_layers",
    "validate_known_dependencies",
    # graph 桥接
    "assert_acyclic",
    "dep_map_from_nodes",
    "index_nodes",
    "layers",
    "parallel_width",
    "ready_ids",
    "to_dag_specs",
    # 基础类型
    "NodeStatus",
    # 节点规格
    "ExecutionNodeSpec",
    "MetadataLayer",
    # 编排协议层 — 图与节点管理器
    "BaseGraphManager",
    "DagGraphManager",
    # 编排协议层 — 计划说明书
    "BasePlanSpec",
    # 编排协议层 — 规划器
    "BasePlanner",
    # 编排协议层 — 重规划器
    "BaseReplanner",
    "ReplanDecision",
    # 编排协议层 — 节点执行器
    "BaseNodeExecutor",
    # 编排协议层 — 事件与结果
    "OrchestratorEvent",
    "OrchestratorResult",
    # 编排协议层 — 编排器
    "BaseOrchestrator",
]
