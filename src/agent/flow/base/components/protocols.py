"""节点运行时可插拔行为的 Protocol 边界。

分两组：
  · 旧九层协议（NodeExecutor / NodeDataIngress / NodeValidator / NodeSecurityFilter）
    — 保持原有签名，供存量代码使用。
  · 新三接口协议（NodeObserver / NodeMutator / ManifestExecutor）
    — 与 NodeManifest + RunnableNode 配套，Planner 通过这三个接口与节点交互。
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, TYPE_CHECKING, runtime_checkable

from .node_spec import ExecutionNodeSpec, NodeManifest, ReviewOutcome, TopologyDecision
from .observation import NodeObservation, ObservationMode
from .verification import VerificationResult

if TYPE_CHECKING:
    from .runtime import NodeExecutionContext, NodeResult
    from agent.flow.base.budget import DecompositionBudget


# ── 旧九层协议（向后兼容） ────────────────────────────────────────────────────


@runtime_checkable
class NodeSecurityFilter(Protocol):
    """L9 横切：在执行流水线前后做权限与审计装饰。"""

    def authorize(self, spec: ExecutionNodeSpec, caller: Mapping[str, Any]) -> None:
        """无权时应 raise。"""

    def audit_event(self, name: str, payload: Mapping[str, Any]) -> None:
        ...


@runtime_checkable
class NodeDataIngress(Protocol):
    """L2：由实现层提供：根据规格构造执行期输入上下文。"""

    def build_inputs(
        self,
        spec: ExecutionNodeSpec,
        upstream_outputs: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        ...


@runtime_checkable
class NodeExecutor(Protocol):
    """L3：由实现层提供（九层规格版）。"""

    def run(
        self,
        spec: ExecutionNodeSpec,
        inputs: Mapping[str, Any],
    ) -> Any:
        ...


@runtime_checkable
class NodeValidator(Protocol):
    """L4：由实现层提供。"""

    def validate(self, spec: ExecutionNodeSpec, output: Any) -> None:
        """校验失败应 raise。"""


# ── 新三接口协议（与 NodeManifest / RunnableNode 配套） ──────────────────────


@runtime_checkable
class NodeObserver(Protocol):
    """接口一：Planner 读取节点的推理链观察。

    默认使用 manifest.observation_mode；
    传入 mode 参数可在单次调用中覆盖。
    """

    def review(self, mode: ObservationMode | None = None) -> NodeObservation:
        ...


@runtime_checkable
class NodeMutator(Protocol):
    """接口二：Planner 在执行前/后向节点注入或修改声明。

    modify() 接受与 NodeManifest 字段同名的 kwargs：
    · 内部通过 dataclasses.replace() 生成新 manifest，保持不变性；
    · 记录 before/after diff，下次 run() 时自动注入 executor 与 verifier 的上下文。
    """

    def modify(self, **kwargs: Any) -> None:
        ...


@runtime_checkable
class ManifestExecutor(Protocol):
    """接口三：节点的纯执行体——把输入变成输出。

    ctx 由 RunnableNode 注入，执行体通过 ctx.on_step 上报每一步 TaoStep；
    不关心调度、重试、持久化。
    """

    def run(
        self,
        manifest: NodeManifest,
        inputs: Mapping[str, Any],
        ctx: "NodeExecutionContext | None" = None,
    ) -> Any:
        ...


# ── 原子规划层 ────────────────────────────────────────────────────────────────


@runtime_checkable
class BaseAtomicPlanner(Protocol):
    """原子规划层：判断节点是否可直接执行，否则决定如何展开。

    位于战略 Planner 与 ManifestExecutor 之间，是粒度收敛的关键一层。

    调用时机
    --------
    Orchestrator 在调度某个节点之前调用 assess()：
    · 若节点已通过 is_atomic() 确定性判断 → 跳过，直接执行。
    · 否则调用 assess()，LLM 给出 TopologyDecision。

    assess() 约定
    -------------
    · kind == atomic  — 节点足够小，可直接执行；sub_manifests 为空。
    · kind == flat    — 展开为 N 个同层兄弟节点；
                        Orchestrator 将 sub_manifests 合并进当前 DAG。
    · kind == nested  — 封装为私有子图；
                        Orchestrator 为子图启动递归编排，
                        output_node_id 指定子图的出口节点。

    budget 参数
    -----------
    传入当前层的 DecompositionBudget；assess() 必须遵守其上限，
    不得生成超过 budget.max_width 个子节点，
    且在 budget.exhausted 时必须返回 atomic。
    """

    async def assess(
        self,
        manifest: "NodeManifest",
        budget: "DecompositionBudget",
        *,
        context: dict | None = None,
    ) -> "TopologyDecision":
        """分析 manifest，返回拓扑决策。

        Parameters
        ----------
        manifest:
            待评估的节点声明（可能尚未填写 input/output_contract）。
        budget:
            当前层预算；exhausted 时必须返回 atomic。
        context:
            可选的上下文信息（上游节点输出、目标描述等）。
        """
        ...


@runtime_checkable
class BaseAtomicReviewer(Protocol):
    """原子规划审查层：对 AtomicPlanner 给出的 TopologyDecision 进行自洽性审查。

    职责与边界
    ----------
    · **仅咨询**：Reviewer 不改变 budget，不触发新的展开；
      它只对已有决策做"合理性验证"并可以给出修订版。
    · **一次审查**：每个 assess() 调用最多触发 budget.max_review_rounds 次审查，
      超限后强制接受当前决策，防止死循环。

    review() 约定
    -------------
    · approved == True   → decision 自洽，直接使用。
    · approved == False，revised 非 None  → 用 revised 替换 decision。
    · approved == False，revised 为 None  → 无法修复，降级为 atomic（保守兜底）。

    审查关注点（实现参考）
    ---------------------
    · sub_manifests 的 I/O 链是否闭合（上游 output_contract 能否满足下游 input_contract）。
    · depends_on 中是否存在隐式循环。
    · topology kind 是否与 manifest 描述的职责范围匹配。
    · sub_manifests 数量是否在 budget.max_width 以内。
    · 拆分是否有实质意义（不是简单改名）。
    """

    async def review(
        self,
        manifest: "NodeManifest",
        decision: "TopologyDecision",
        budget: "DecompositionBudget",
        *,
        context: dict | None = None,
    ) -> "ReviewOutcome":
        """审查 decision，返回审查结果。

        Parameters
        ----------
        manifest:
            原始节点声明（AtomicPlanner 的输入）。
        decision:
            AtomicPlanner 给出的拓扑决策。
        budget:
            当前层预算，用于检查 width 合规性。
        context:
            可选上下文，与 AtomicPlanner.assess() 的 context 参数一致。
        """
        ...


@runtime_checkable
class NodeVerifier(Protocol):
    """Verifier 层：检查节点输出，返回结构化校验报告。

    两类检查
    --------
    · abstract（结构 / 类型）：output 的形态是否符合 manifest.output_contract 的声明；
      典型实现：判断是否为 dict / list / str，是否含必要字段。
    · concrete（内容 / 语义）：output 的实际内容是否合理、完整；
      典型实现：LLM 打分、断言关键字、数值范围校验。

    返回的 VerificationResult 由 RunnableNode 挂载到 NodeResult.verification，
    并注入 NodeObservation，最终传回 Planner。
    """

    def verify(
        self,
        manifest: NodeManifest,
        output: Any,
        observation: NodeObservation,
    ) -> VerificationResult:
        ...


@runtime_checkable
class NodeDocumentWriter(Protocol):
    """文档写入层：将节点最终结果（含校验报告）持久化到对应文档。

    write() 在 RunnableNode.run() 的最后一步调用，
    接收完整的 NodeResult（output + verification + observation + logs）。
    实现可以写 JSON 文件、数据库记录、或计划文档中的节点条目。
    """

    def write(
        self,
        manifest: NodeManifest,
        result: "NodeResult",
    ) -> None:
        ...
