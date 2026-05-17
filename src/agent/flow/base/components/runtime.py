"""运行时对象：组合「声明式规格 + 执行策略」，与 :class:`ExecutionNodeSpec` 分离。

两组类型：

旧九层组（向后兼容）
  RunnableExecutionNode          — spec + executor，最小可运行单元
  RunnableExecutionNodeWithHooks — 附加 L2/L4/L9 横切钩子

新三接口组（与 NodeManifest 配套）
  NodeExecutionContext  — 执行上下文，含 TaoStep 回调、纠错指令、manifest diff
  NodeResult           — 节点执行结果，含观察链、校验报告、日志
  RunnableNode         — 对外暴露三个接口：run() / review() / modify()
                         executor 与 verifier 在内部通过 NodeRuntimeManager 线程池调度
"""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping

from ..types import NodeStatus
from .node_spec import ExecutionNodeSpec, NodeManifest
from .observation import NodeObservation, ObservationMode, TaoStep
from .protocols import (
    ManifestExecutor,
    NodeDataIngress,
    NodeDocumentWriter,
    NodeExecutor,
    NodeSecurityFilter,
    NodeValidator,
    NodeVerifier,
)
from .verification import VerificationResult


# ── 旧九层组（向后兼容） ──────────────────────────────────────────────────────


@dataclass
class RunnableExecutionNode:
    spec: ExecutionNodeSpec
    executor: NodeExecutor

    @property
    def task_id(self) -> str:
        return self.spec.task_id

    def run(self, inputs: Mapping[str, Any]) -> Any:
        return self.executor.run(self.spec, inputs)


@dataclass
class RunnableExecutionNodeWithHooks:
    spec: ExecutionNodeSpec
    executor: NodeExecutor
    ingress: NodeDataIngress | None = None
    validator: NodeValidator | None = None
    security: NodeSecurityFilter | None = None

    def run(
        self,
        caller: Mapping[str, Any],
        upstream_outputs: Mapping[str, Any],
    ) -> Any:
        if self.security is not None:
            self.security.authorize(self.spec, caller)
            self.security.audit_event("node_start", {"task_id": self.spec.task_id})
        inputs = (
            self.ingress.build_inputs(self.spec, upstream_outputs)
            if self.ingress is not None
            else upstream_outputs
        )
        out = self.executor.run(self.spec, inputs)
        if self.validator is not None:
            self.validator.validate(self.spec, out)
        if self.security is not None:
            self.security.audit_event("node_end", {"task_id": self.spec.task_id})
        return out


# ── 新三接口组 ────────────────────────────────────────────────────────────────


class LogLevel(str, Enum):
    info = "info"
    warn = "warn"
    error = "error"


@dataclass(frozen=True)
class LogEntry:
    """节点执行的结构化日志行。

    timestamp  ISO-8601 UTC，精确到毫秒。
    level      info / warn / error。
    source     产生来源，如 "executor"、"verifier"。
    message    日志正文，限 512 字符以内（写入时自动截断）。
    """

    timestamp: str
    level: LogLevel
    source: str
    message: str

    @classmethod
    def make(
        cls,
        message: str,
        *,
        level: LogLevel = LogLevel.info,
        source: str = "node",
    ) -> LogEntry:
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        return cls(
            timestamp=ts,
            level=level,
            source=source,
            message=message[:512],
        )

    def __str__(self) -> str:
        return f"[{self.timestamp}] [{self.level.value.upper()}] [{self.source}] {self.message}"


@dataclass
class NodeExecutionContext:
    """执行器与节点之间的运行时通道。

    executor / verifier 通过本对象获得：
    · on_step        — 上报每轮 TaoStep（由 RunnableNode 收集）
    · on_progress    — 上报任意进度文本（可选）
    · corrections    — verifier 上一轮产出的纠错指令；非空说明这是 re-run
    · manifest_diff  — modify() 记录的 before/after diff；
                       {field: (before_val, after_val)}，executor 可据此调整行为
    """

    task_id: str
    on_step: Callable[[TaoStep], None] | None = None
    on_progress: Callable[[str], None] | None = None
    corrections: list[str] = field(default_factory=list)
    manifest_diff: dict[str, Any] = field(default_factory=dict)


@dataclass
class NodeResult:
    """节点单次执行的完整结果，含观察链与校验报告。

    字段说明
    --------
    output          executor 的原始返回值。
    error           执行异常信息（由外层 Orchestrator 填入，节点内部不捕获）。
    elapsed_seconds 执行耗时（秒）。
    observation     节点推理链观察（含 verification_report 嵌入文本）。
    verification    结构化校验报告（VerificationResult）；无 verifier 时为 skip 占位。
    log_entries     按时序的日志行，供 NodeDocumentWriter 持久化。
    """

    task_id: str
    status: NodeStatus
    output: Any = None
    error: str | None = None
    elapsed_seconds: float | None = None
    observation: NodeObservation | None = None
    verification: VerificationResult | None = None
    log_entries: list[LogEntry] = field(default_factory=list)


_ERROR_KEYWORDS: frozenset[str] = frozenset(
    {"error", "fail", "exception", "traceback", "invalid", "wrong", "cannot"}
)


class RunnableNode:
    """单个可执行节点，对 Planner 暴露三个公开接口：

    run(inputs)        — 完整执行流程，返回 NodeResult
    review(mode?)      — 读取推理链观察（Planner 调用）
    modify(**kwargs)   — 修改 manifest 字段，记录 diff，下次 run() 时注入执行上下文

    executor 与 verifier 不对外暴露，在 run() 内部通过 NodeRuntimeManager 线程池调度。

    run() 内部执行顺序
    ------------------
    ① [executor_pool] executor.run(manifest, inputs, ctx)
       · ctx 携带 manifest_diff（来自 modify()）
    ② [verifier_pool] verifier.verify(manifest, output, observation)
       · 异步于 executor：executor 完成后立即提交 verifier 到独立线程池
       · 无 verifier → VerificationResult.skip() 占位
    ③ 纠错循环（若 verification.corrections 非空，最多执行一次）：
       · [executor_pool] executor.run(manifest, inputs, correction_ctx)
         correction_ctx.corrections = verifier 的纠错指令
       · [verifier_pool] verifier.verify(...) 重新校验
    ④ 构建最终 NodeObservation（含 verification_report）
    ⑤ 汇总 log_entries
    ⑥ doc_writer.write()（若配置）
    ⑦ 返回 NodeResult，清空 _pending_diff

    异常
    ----
    executor / verifier 的异常直接向上传播，由 Orchestrator 负责状态标记。
    """

    def __init__(
        self,
        manifest: NodeManifest,
        executor: ManifestExecutor,
        verifier: NodeVerifier | None = None,
        doc_writer: NodeDocumentWriter | None = None,
    ) -> None:
        self._manifest = manifest
        self._executor = executor
        self._verifier = verifier
        self._doc_writer = doc_writer
        self._steps: list[TaoStep] = []
        self._result: NodeResult | None = None
        self._pending_diff: dict[str, tuple[Any, Any]] = {}

    # ── 接口一：run ───────────────────────────────────────────────────────────

    def run(self, inputs: Mapping[str, Any]) -> NodeResult:
        diff = dict(self._pending_diff)
        self._pending_diff.clear()

        t0 = time.monotonic()

        # Phase 1: executor（via executor_pool）
        output = self._call_executor(inputs, diff=diff, corrections=[])

        # Phase 2: verifier（via verifier_pool，executor 完成后异步提交）
        if self._verifier is not None:
            verification = self._call_verifier(output)

            # Phase 3: 纠错循环（最多一次）
            if verification.corrections:
                output = self._call_executor(
                    inputs, diff=diff, corrections=verification.corrections
                )
                verification = self._call_verifier(output)
        else:
            verification = VerificationResult.skip()

        # Phase 4: 构建最终结果
        obs = self._build_observation(
            verification_report=verification.to_planner_report()
        )
        step_logs: list[LogEntry] = [
            LogEntry.make(
                f"[step {s.index}] {s.action}: {s.observation[:200]}",
                source="executor",
            )
            for s in self._steps
        ]
        verif_logs: list[LogEntry] = [
            LogEntry.make(entry, source="verifier")
            for entry in verification.log_entries
        ]

        # abstract 检查失败（结构/类型不符）→ 节点视为 failed，错误携带完整报告
        from .verification import VerificationStatus
        node_status = (
            NodeStatus.failed
            if verification.status == VerificationStatus.failed
            else NodeStatus.done
        )
        node_error = verification.report if node_status == NodeStatus.failed else None

        result = NodeResult(
            task_id=self._manifest.task_id,
            status=node_status,
            output=output,
            error=node_error,
            elapsed_seconds=time.monotonic() - t0,
            observation=obs,
            verification=verification,
            log_entries=step_logs + verif_logs,
        )

        # doc_writer fire-and-forget：写入不阻塞 run() 返回
        if self._doc_writer is not None:
            from infra.node_runtime import NodeRuntimeManager
            NodeRuntimeManager.global_instance().submit_doc_write(
                self._doc_writer.write, self._manifest, result
            )

        self._result = result
        return result

    # ── 接口二：review ────────────────────────────────────────────────────────

    def review(self, mode: ObservationMode | None = None) -> NodeObservation:
        """Planner 读取本节点的推理链观察。

        可在 run() 前（返回空观察）或 run() 后（返回完整观察含校验报告）调用。
        """
        verif_report = (
            self._result.verification.to_planner_report()
            if self._result and self._result.verification
            else ""
        )
        return self._build_observation(mode=mode, verification_report=verif_report)

    # ── 接口三：modify ────────────────────────────────────────────────────────

    def modify(self, **kwargs: Any) -> None:
        """Planner 修改节点的 manifest 字段，记录 before/after diff。

        diff 在下次 run() 时注入 NodeExecutionContext，
        executor 和 verifier 可据此感知变化并调整行为。
        """
        for key, new_val in kwargs.items():
            before_val = getattr(self._manifest, key)
            self._pending_diff[key] = (before_val, new_val)
        self._manifest = dataclasses.replace(self._manifest, **kwargs)

    # ── 属性 ──────────────────────────────────────────────────────────────────

    @property
    def manifest(self) -> NodeManifest:
        return self._manifest

    @property
    def result(self) -> NodeResult | None:
        return self._result

    @property
    def task_id(self) -> str:
        return self._manifest.task_id

    # ── 内部：executor 调度 ───────────────────────────────────────────────────

    def _call_executor(
        self,
        inputs: Mapping[str, Any],
        diff: dict[str, tuple[Any, Any]],
        corrections: list[str],
    ) -> Any:
        steps: list[TaoStep] = []

        def _on_step(step: TaoStep) -> None:
            steps.append(step)

        ctx = NodeExecutionContext(
            task_id=self._manifest.task_id,
            on_step=_on_step,
            corrections=corrections,
            manifest_diff=diff,
        )
        from infra.node_runtime import NodeRuntimeManager
        output = NodeRuntimeManager.global_instance().submit_executor(
            self._executor.run, self._manifest, inputs, ctx
        ).result()

        self._steps = steps   # 保留本轮 steps（纠错后覆盖为最新一轮）
        return output

    # ── 内部：verifier 调度 ───────────────────────────────────────────────────

    def _call_verifier(self, output: Any) -> VerificationResult:
        obs = self._build_observation()
        from infra.node_runtime import NodeRuntimeManager
        return NodeRuntimeManager.global_instance().submit_verifier(
            self._verifier.verify, self._manifest, output, obs   # type: ignore[union-attr]
        ).result()

    # ── 内部：观察构建 ────────────────────────────────────────────────────────

    def _build_observation(
        self,
        mode: ObservationMode | None = None,
        verification_report: str = "",
    ) -> NodeObservation:
        effective_mode = mode if mode is not None else self._manifest.observation_mode
        raw = (self._result.output or self._result.error or "") if self._result else ""
        summary = str(raw)[:500]

        if effective_mode == ObservationMode.full:
            return NodeObservation(
                task_id=self._manifest.task_id,
                mode=effective_mode,
                steps=list(self._steps),
                summary=summary,
                step_count=len(self._steps),
                verification_report=verification_report,
            )

        key_steps = self._distill(self._steps)
        return NodeObservation(
            task_id=self._manifest.task_id,
            mode=effective_mode,
            steps=key_steps,
            summary=summary,
            step_count=len(self._steps),
            key_decisions=[
                f"Step {s.index}: {s.thought[:120]}" for s in key_steps if s.thought
            ],
            verification_report=verification_report,
        )

    # ── 内部：蒸馏逻辑 ────────────────────────────────────────────────────────

    @staticmethod
    def _distill(steps: list[TaoStep]) -> list[TaoStep]:
        if len(steps) <= 2:
            return list(steps)
        key: list[TaoStep] = [steps[0]]
        for s in steps[1:-1]:
            if any(kw in s.observation.lower() for kw in _ERROR_KEYWORDS):
                key.append(s)
        key.append(steps[-1])
        return key
