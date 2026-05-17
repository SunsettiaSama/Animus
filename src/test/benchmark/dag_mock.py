"""dag_mock.py — DagOrchestrator benchmark 专用 Mock 组件。

组件清单
--------
MockManifestExecutor   脚本化执行器，按 task_id 返回预设输出。
MockNodeVerifier       按 task_id 集合强制节点失败，其余节点通过。
MockAtomicPlanner      按 task_id 返回预设 TopologyDecision，默认 atomic。
ScriptedReplanner      按 trigger 返回预设 ReplanDecision。
StaticManifestPlanner  直接返回传入的 ManifestPlanSpec，供无 LLM 测试使用。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Mapping

_SRC = Path(__file__).resolve().parent.parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agent.flow.base.budget import DecompositionBudget, TopologyKind
from agent.flow.base.components.node_spec import NodeManifest, TopologyDecision
from agent.flow.base.components.verification import (
    VerificationCheck,
    VerificationResult,
    VerificationStatus,
    CheckKind,
)
from agent.flow.base.orchestration import ReplanDecision


# ── MockManifestExecutor ──────────────────────────────────────────────────────


class MockManifestExecutor:
    """ManifestExecutor 实现：按 task_id / tool_package 返回预设输出。

    查找顺序：task_id → tool_package → default_output。
    """

    def __init__(
        self,
        output_map: dict[str, str] | None = None,
        default_output: str = "mock_output",
    ) -> None:
        self._map: dict[str, str] = output_map or {}
        self._default = default_output

    def run(
        self,
        manifest: NodeManifest,
        inputs: Mapping[str, Any],
        ctx: Any = None,
    ) -> str:
        key_tid = manifest.task_id
        key_pkg = manifest.tool_package or ""
        return self._map.get(key_tid, self._map.get(key_pkg, self._default))


# ── MockNodeVerifier ──────────────────────────────────────────────────────────


class MockNodeVerifier:
    """NodeVerifier 实现：failing_ids 中的节点返回 failed，其余通过。"""

    def __init__(self, failing_ids: set[str] | None = None) -> None:
        self._failing: set[str] = failing_ids or set()

    def verify(
        self,
        manifest: NodeManifest,
        output: Any,
        observation: Any,
    ) -> VerificationResult:
        if manifest.task_id in self._failing:
            return VerificationResult(
                status=VerificationStatus.failed,
                verdict="[FAILED] forced by MockNodeVerifier",
                checks=[
                    VerificationCheck(
                        name="mock_fail",
                        passed=False,
                        kind=CheckKind.abstract,
                        detail=f"task_id {manifest.task_id!r} is in failing_ids",
                    )
                ],
                report=f"MockNodeVerifier forced failure for {manifest.task_id!r}",
                corrections=[],
                log_entries=[],
            )
        return VerificationResult.skip()


# ── MockAtomicPlanner ─────────────────────────────────────────────────────────


class MockAtomicPlanner:
    """BaseAtomicPlanner 实现：按 task_id 返回预设 TopologyDecision，默认 atomic。"""

    def __init__(
        self,
        decisions: dict[str, TopologyDecision] | None = None,
    ) -> None:
        self._decisions: dict[str, TopologyDecision] = decisions or {}

    async def assess(
        self,
        manifest: NodeManifest,
        budget: DecompositionBudget,
        *,
        context: dict | None = None,
    ) -> TopologyDecision:
        if budget.exhausted:
            return TopologyDecision(
                kind=TopologyKind.atomic,
                reason="budget exhausted — forced atomic",
                sub_manifests=(),
                output_node_id="",
            )
        if manifest.task_id in self._decisions:
            return self._decisions[manifest.task_id]
        return TopologyDecision(
            kind=TopologyKind.atomic,
            reason="mock default: atomic",
            sub_manifests=(),
            output_node_id="",
        )


# ── ScriptedReplanner ─────────────────────────────────────────────────────────


class ScriptedReplanner:
    """BaseReplanner 实现：按 trigger 返回预设 ReplanDecision。

    未配置 trigger 时默认返回 done（不修改 spec）。
    """

    def __init__(
        self,
        decisions: dict[str, ReplanDecision] | None = None,
        triggers: set[str] | None = None,
    ) -> None:
        self._decisions: dict[str, ReplanDecision] = decisions or {}
        self._triggers: set[str] = triggers or set(self._decisions)

    async def replan(
        self,
        spec: Any,
        graph: Any,
        *,
        trigger: str,
        cycle: int = 0,
    ) -> ReplanDecision:
        if trigger in self._decisions:
            return self._decisions[trigger]
        return ReplanDecision(decision="done", conclusion="scripted: no-op done")

    def should_trigger(self, trigger: str) -> bool:
        return trigger in self._triggers


# ── StaticManifestPlanner ─────────────────────────────────────────────────────


class StaticManifestPlanner:
    """BasePlanner 实现：直接返回构造时传入的 ManifestPlanSpec。"""

    def __init__(self, spec: Any) -> None:
        self._spec = spec

    async def plan(
        self,
        goal: str,
        *,
        context: dict | None = None,
        step_callback: Any = None,
    ) -> Any:
        return self._spec
