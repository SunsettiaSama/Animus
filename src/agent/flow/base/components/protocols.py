"""节点运行时可插拔行为的 Protocol 边界。

分两组：
  · 旧九层协议（NodeExecutor / NodeDataIngress / NodeValidator / NodeSecurityFilter）
    — 保持原有签名，供存量代码使用。
  · 新三接口协议（NodeObserver / NodeMutator / ManifestExecutor）
    — 与 NodeManifest + RunnableNode 配套，Planner 通过这三个接口与节点交互。
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol, TYPE_CHECKING, runtime_checkable

from .node_spec import ExecutionNodeSpec, NodeManifest
from .observation import NodeObservation, ObservationMode
from .verification import VerificationResult

if TYPE_CHECKING:
    from .runtime import NodeExecutionContext, NodeResult


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


# ── Verifier 与文档写入 ───────────────────────────────────────────────────────


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
