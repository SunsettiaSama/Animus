from __future__ import annotations

# ── 观察层 ────────────────────────────────────────────────────────────────────
from .observation import NodeObservation, ObservationMode, TaoStep

# ── 校验层 ────────────────────────────────────────────────────────────────────
from .verification import (
    CheckKind,
    VerificationCheck,
    VerificationResult,
    VerificationStatus,
)

# ── 节点规格（旧九层 + 新精简 Manifest） ─────────────────────────────────────
from .node_spec import (
    AssertionSpec,
    BranchSpec,
    CompensationAction,
    ControlFlowLayer,
    DataIngressLayer,
    ErrorSeverity,
    ExecutionLayer,
    ExecutionNodeSpec,
    ExternalMount,
    FanoutSpec,
    FaultToleranceLayer,
    MetadataLayer,
    NodeManifest,
    ObservabilityLayer,
    ResourceHints,
    RetryPolicy,
    SchemaRef,
    SecurityAuditLayer,
    StatePersistenceLayer,
    SubDagRef,
    UpstreamBinding,
    ValidationLayer,
    node_specs_to_dag_edges,
    validate_node_graph_ids,
)

# ── 协议（旧九层 + 新三接口） ─────────────────────────────────────────────────
from .protocols import (
    ManifestExecutor,
    NodeDataIngress,
    NodeDocumentWriter,
    NodeExecutor,
    NodeMutator,
    NodeObserver,
    NodeSecurityFilter,
    NodeValidator,
    NodeVerifier,
)

# ── 运行时（旧九层 + 新三接口） ───────────────────────────────────────────────
from .runtime import (
    LogEntry,
    LogLevel,
    NodeExecutionContext,
    NodeResult,
    RunnableExecutionNode,
    RunnableExecutionNodeWithHooks,
    RunnableNode,
)

__all__ = [
    # observation
    "NodeObservation",
    "ObservationMode",
    "TaoStep",
    # verification
    "CheckKind",
    "VerificationCheck",
    "VerificationResult",
    "VerificationStatus",
    # node spec — legacy
    "AssertionSpec",
    "BranchSpec",
    "CompensationAction",
    "ControlFlowLayer",
    "DataIngressLayer",
    "ErrorSeverity",
    "ExecutionLayer",
    "ExecutionNodeSpec",
    "ExternalMount",
    "FanoutSpec",
    "FaultToleranceLayer",
    "MetadataLayer",
    "ObservabilityLayer",
    "ResourceHints",
    "RetryPolicy",
    "SchemaRef",
    "SecurityAuditLayer",
    "StatePersistenceLayer",
    "SubDagRef",
    "UpstreamBinding",
    "ValidationLayer",
    "node_specs_to_dag_edges",
    "validate_node_graph_ids",
    # node spec — new
    "NodeManifest",
    # protocols — legacy
    "NodeDataIngress",
    "NodeExecutor",
    "NodeSecurityFilter",
    "NodeValidator",
    # protocols — new
    "ManifestExecutor",
    "NodeDocumentWriter",
    "NodeMutator",
    "NodeObserver",
    "NodeVerifier",
    # runtime — legacy
    "RunnableExecutionNode",
    "RunnableExecutionNodeWithHooks",
    # runtime — new
    "LogEntry",
    "LogLevel",
    "NodeExecutionContext",
    "NodeResult",
    "RunnableNode",
]
