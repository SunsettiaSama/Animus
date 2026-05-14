"""九层执行节点静态规格（声明式）；调度与真正执行由 agent.flow 实现层完成。

本模块仅描述「节点应携带哪些配置切面」，不发起 I/O、不导入 ReAct。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

from agent.flow.base.components.observation import ObservationMode


# ── Shared primitives ─────────────────────────────────────────────────────────


class ErrorSeverity(str, Enum):
    """L5 与 L4 配合：错误如何被归类。"""

    retryable = "retryable"
    degrade = "degrade"
    fatal = "fatal"


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 1
    initial_backoff_seconds: float = 0.0
    max_backoff_seconds: float | None = None


@dataclass(frozen=True)
class ResourceHints:
    """声明式资源需求（调度器可映射为 K8s limits / queue 权重）。"""

    cpu_millicores: int | None = None
    memory_mib: int | None = None
    gpu_count: int | None = None
    gpu_type: str | None = None


@dataclass(frozen=True)
class SchemaRef:
    """输入/输出 Schema 的外部引用（JSON Schema URI、注册表 ID 等）。"""

    uri: str | None = None
    name: str | None = None
    version: str | None = None


# ── L1 元数据层 ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class MetadataLayer:
    """L1：静态定义与声明式规范。"""

    task_id: str
    node_type: str = "task"
    depends_on: tuple[str, ...] = ()
    input_schema: SchemaRef | None = None
    output_schema: SchemaRef | None = None
    retry_policy: RetryPolicy | None = None
    timeout_seconds: float | None = None
    resources: ResourceHints | None = None
    priority: int = 0
    tags: dict[str, str] = field(default_factory=dict)


# ── L2 数据接入层 ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UpstreamBinding:
    """从上游节点或命名通道取数。"""

    source_task_id: str | None = None
    output_key: str = "default"
    transform: str | None = None


@dataclass(frozen=True)
class ExternalMount:
    """外部数据挂载说明（路径、KV 前缀、bucket key 等）。"""

    kind: str
    uri_or_path: str
    read_only: bool = True
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DataIngressLayer:
    """L2：拉取输入、反序列化、完整性校验、挂载外部数据、运行时配置注入。"""

    upstream: tuple[UpstreamBinding, ...] = ()
    mounts: tuple[ExternalMount, ...] = ()
    strict_input_validation: bool = True
    runtime_config_overlay: dict[str, Any] = field(default_factory=dict)


# ── L3 执行层 ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExecutionLayer:
    """L3：业务执行方式（实现层解析 kind 并调度）。"""

    kind: str = "inline"
    entrypoint: str | None = None
    image: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    working_dir: str | None = None
    capture_logs: bool = True
    progress_report_interval_seconds: float | None = None
    resources: ResourceHints | None = None


# ── L4 检验层 ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AssertionSpec:
    """业务断言占位（具体语义由实现层解释）。"""

    name: str
    kind: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ValidationLayer:
    """L4：输出正确性校验与签名校验。"""

    enforce_output_schema: bool = True
    assertions: tuple[AssertionSpec, ...] = ()
    output_hash_algorithm: str | None = None


# ── L5 容错与补偿层 ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CompensationAction:
    """补偿或告警动作的描述符。"""

    kind: str
    target: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FaultToleranceLayer:
    """L5：错误分级、DLQ、补偿、幂等。"""

    severity_map: dict[str, ErrorSeverity] = field(default_factory=dict)
    dlq_channel: str | None = None
    compensations: tuple[CompensationAction, ...] = ()
    idempotency_key_template: str | None = None


# ── L6 控制流扩展层 ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BranchSpec:
    """条件分支（实现层求值表达式或策略 ID）。"""

    condition_ref: str
    then_target_task_id: str | None = None
    else_target_task_id: str | None = None


@dataclass(frozen=True)
class FanoutSpec:
    """动态扇出：按输入项数或模板生成子任务。"""

    mode: str = "per_item"
    item_path: str | None = None
    max_children: int | None = None


@dataclass(frozen=True)
class SubDagRef:
    """嵌套子 DAG 引用。"""

    flow_name: str
    version: str | None = None
    inputs_map: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ControlFlowLayer:
    """L6：DAG 之外的分支、扇出、循环元数据、子图调用。"""

    branches: tuple[BranchSpec, ...] = ()
    fanout: FanoutSpec | None = None
    batch_iteration: dict[str, Any] = field(default_factory=dict)
    sub_dag: SubDagRef | None = None
    control_output_field: str = "_control"


# ── L7 状态持久化层 ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StatePersistenceLayer:
    """L7：状态上报、输出下沉、检查点。"""

    state_sink: str | None = None
    output_sink: str | None = None
    checkpoint_interval_seconds: float | None = None
    checkpoint_after_success: bool = True


# ── L8 可观测性层 ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ObservabilityLayer:
    """L8：指标与结构化事件（与 L7 面向调度/下游不同，本层面向运维）。"""

    metric_prefix: str | None = None
    custom_metrics: dict[str, str] = field(default_factory=dict)
    trace_span_name: str | None = None
    log_event_kinds: tuple[str, ...] = (
        "start",
        "end",
        "retry",
        "skip",
        "degraded",
    )


# ── L9 安全与审计层 ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SecurityAuditLayer:
    """L9：权限、脱敏、审计维度（横切，可在运行时包装为 filter）。"""

    required_roles: tuple[str, ...] = ()
    redact_paths: tuple[str, ...] = ()
    audit_labels: dict[str, str] = field(default_factory=dict)
    encryption_required: bool = False
    sandbox_profile: str | None = None


# ── Composite ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ExecutionNodeSpec:
    """完整九层节点规格：仅 L1 必选，其余层可选。"""

    metadata: MetadataLayer
    data_ingress: DataIngressLayer | None = None
    execution: ExecutionLayer | None = None
    validation: ValidationLayer | None = None
    fault_tolerance: FaultToleranceLayer | None = None
    control_flow: ControlFlowLayer | None = None
    state_persistence: StatePersistenceLayer | None = None
    observability: ObservabilityLayer | None = None
    security_audit: SecurityAuditLayer | None = None

    @property
    def task_id(self) -> str:
        return self.metadata.task_id

    @property
    def depends_on(self) -> tuple[str, ...]:
        return self.metadata.depends_on


@dataclass(frozen=True)
class NodeManifest:
    """节点执行手册：executor 运行一个节点所需的全部声明，无需查询任何外部配置。

    ── 身份与依赖（调度层使用） ───────────────────────────────────────────────
    task_id       唯一标识，DAG 边依赖它。
    depends_on    上游节点 ID 列表；运行时输入由这些节点的输出组成。

    ── 任务语义（Planner 与 executor 共同使用） ─────────────────────────────
    description     自然语言任务说明，LLM 可直接理解。
    input_contract  对上游输入的期望（自然语言）；Planner 用于推理依赖合法性，
                    executor 用于理解可用数据的形态。
    output_contract 对产出物的约定（自然语言）；executor 知道该产出什么，
                    Planner / Replanner 用于验证结果是否符合预期。

    ── Executor 执行参数（executor 直接读取，无需 Profile 查表） ────────────
    tool_package  引用已注册的 ToolPackage 名称（如 "executor" / "researcher"）；
                  为 None 时 executor 使用自身默认工具集。
    max_steps     TAO 循环最大步数上限；为 None 时 executor 使用 Profile 默认值。
    system_note   追加到 executor 系统提示词末尾的任务级上下文；
                  适合放任务特有的约束、格式要求、注意事项。

    ── 可观测性（Planner 观察节点时使用） ──────────────────────────────────
    observation_mode  向 Planner 暴露的推理链粒度：distilled（默认）或 full。

    ── 扩展元数据 ───────────────────────────────────────────────────────────
    tags  任意 key-value 标注，供 Planner / WebUI / 监控等消费；
          不影响执行逻辑。
    """

    task_id: str
    description: str
    depends_on: tuple[str, ...] = ()
    input_contract: str = ""
    output_contract: str = ""
    tool_package: str | None = None
    max_steps: int | None = None
    system_note: str = ""
    observation_mode: ObservationMode = ObservationMode.distilled
    tags: dict[str, str] = field(default_factory=dict)


def node_specs_to_dag_edges(
    nodes: Sequence[ExecutionNodeSpec],
) -> dict[str, frozenset[str]]:
    """由九层规格提取调度器可用的依赖边 mapping[task_id]->deps."""
    return {n.task_id: frozenset(n.depends_on) for n in nodes}


def validate_node_graph_ids(nodes: Sequence[ExecutionNodeSpec]) -> None:
    """校验 task_id 唯一且 depends_on 均指向图中已知节点。"""
    ids = {n.task_id for n in nodes}
    if len(ids) != len(nodes):
        raise ValueError("duplicate task_id in ExecutionNodeSpec list")
    for n in nodes:
        for d in n.depends_on:
            if d not in ids:
                raise ValueError(f"task {n.task_id!r} depends_on unknown id {d!r}")
