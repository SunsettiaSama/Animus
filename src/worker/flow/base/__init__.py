from __future__ import annotations

# ── 预算与拓扑 ────────────────────────────────────────────────────────────────
from .budget import DecompositionBudget, TopologyKind, is_atomic

# ── 注册表 ────────────────────────────────────────────────────────────────────
from .registry import (
    NodeRegistry, ExecutorFactory, VerifierFactory,
    AtomicPlannerFactory, AtomicReviewerFactory, get_registry,
)
from .defaults import SubAgentManifestExecutor, register_defaults, _build_llm_call
from .components.atomic_planner import AtomicPlanner, LlmCallFn
from .components.atomic_reviewer import AtomicReviewer

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

# ── 基础类型 ──────────────────────────────────────────────────────────────────
from .types import NodeStatus

# ── 编排协议层 ────────────────────────────────────────────────────────────────
from .orchestration import (
    # 图与节点管理器
    BaseGraphManager,
    DagGraphManager,
    # 计划说明书
    BasePlanSpec,
    ManifestAwarePlanSpec,
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

# ── DEPRECATED: 九层 ExecutionNodeSpec → graph 桥接 ──────────────────────────
# 以下导出仅供旧测试过渡期使用；新代码请直接使用 ManifestPlanSpec + DagOrchestrator。
# 待 src/test/agent/flow/test_link.py 等测试迁移完成后将移除。
from .link import (
    assert_acyclic,
    dep_map_from_nodes,
    index_nodes,
    layers,
    parallel_width,
    ready_ids,
    to_dag_specs,
)
from .components import ExecutionNodeSpec, MetadataLayer

# ── 具体计划说明书 ─────────────────────────────────────────────────────────────
from .plan_spec import ManifestPatch, ManifestPlanSpec

# ── 具体编排器 ────────────────────────────────────────────────────────────────
from .dag_orchestrator import DagOrchestrator

__all__ = [
    # 预算与拓扑
    "DecompositionBudget",
    "TopologyKind",
    "is_atomic",
    # 注册表
    "NodeRegistry",
    "ExecutorFactory",
    "VerifierFactory",
    "AtomicPlannerFactory",
    "AtomicReviewerFactory",
    "get_registry",
    "SubAgentManifestExecutor",
    "register_defaults",
    "_build_llm_call",
    # 原子规划层
    "AtomicPlanner",
    "AtomicReviewer",
    "LlmCallFn",
    # DAG 图算法
    "DagNodeSpec",
    "edges_from_specs",
    "finished_for_dependencies",
    "has_cycle",
    "max_parallel_width",
    "ready_node_ids",
    "topological_layers",
    "validate_known_dependencies",
    # 基础类型
    "NodeStatus",
    # 编排协议层 — 图与节点管理器
    "BaseGraphManager",
    "DagGraphManager",
    # 编排协议层 — 计划说明书
    "BasePlanSpec",
    "ManifestAwarePlanSpec",
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
    # 具体计划说明书
    "ManifestPatch",
    "ManifestPlanSpec",
    # 具体编排器
    "DagOrchestrator",
    # DEPRECATED — 九层 ExecutionNodeSpec 桥接（待移除）
    "assert_acyclic",
    "dep_map_from_nodes",
    "index_nodes",
    "layers",
    "parallel_width",
    "ready_ids",
    "to_dag_specs",
    "ExecutionNodeSpec",
    "MetadataLayer",
]
