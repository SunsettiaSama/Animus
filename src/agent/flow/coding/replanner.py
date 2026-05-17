from __future__ import annotations

import asyncio
from typing import Any, Callable

from agent.flow.base.types import NodeStatus

LlmCallFn = Callable[[str, str], str]

# ── System prompts ────────────────────────────────────────────────────────────

_SYSTEM_CONCLUDE = """\
You are a software project lead. Below are the results of a code generation task.
Write a concise project summary covering:
  - What was built and its purpose
  - Key design decisions made
  - Outstanding issues or next steps (if any)
Keep it under 300 words. Plain text, no JSON.
"""

_SYSTEM_DIAGNOSE = """\
You are a software debugger. A coding DAG node has failed.
Analyze the failed node's description and any available context,
then decide: should the task ABORT or can it be PATCHED?
Output a single JSON object: {{"decision": "abort"|"patch", "reason": str}}
"""


# ── CodeReplanner ─────────────────────────────────────────────────────────────

class CodeReplanner:
    """BaseReplanner 实现 — 决定编码 DAG 在失败或完成后如何处置。

    触发点：
        on_plan_complete  — 所有节点执行成功，LLM 汇总综合结论后返回 done。
        on_task_failed    — 某个节点失败；保守策略：直接 abort，避免在错误上叠加错误。

    返回 ReplanDecision 格式（与 base Orchestrator 约定一致）：
        {"decision": "done"|"abort"|"modify", "conclusion": str, "patch": ...}
    """

    def __init__(self, llm_call: LlmCallFn, max_cycles: int = 1) -> None:
        self._llm = llm_call
        self._max_cycles = max_cycles

    def should_trigger(self, trigger: str) -> bool:
        return trigger in {"on_task_failed", "on_plan_complete"}

    async def replan(
        self,
        spec: Any,         # BasePlanSpec / ManifestPlanSpec
        graph: Any,        # DagGraphManager
        *,
        trigger: str,
        cycle: int = 0,
    ) -> Any:              # ReplanDecision
        from agent.flow.base.dag_orchestrator import ReplanDecision

        if trigger == "on_plan_complete":
            loop = asyncio.get_running_loop()
            conclusion = await loop.run_in_executor(
                None, self._conclude_sync, spec, graph
            )
            return ReplanDecision(decision="done", conclusion=conclusion)

        if trigger == "on_task_failed":
            failed_ids = [
                nid
                for nid in _all_node_ids(spec)
                if _node_status(graph, nid) == NodeStatus.failed
            ]
            conclusion = (
                f"节点 {failed_ids} 执行失败，中止编码任务。"
                if failed_ids
                else "未知节点失败，中止编码任务。"
            )
            return ReplanDecision(decision="abort", conclusion=conclusion)

        return ReplanDecision(decision="abort", conclusion="未知触发，中止。")

    # ── 内部 ──────────────────────────────────────────────────────────────────

    def _conclude_sync(self, spec: Any, graph: Any) -> str:
        parts: list[str] = [f"Goal: {_objective(spec)}", ""]
        for nid in _all_node_ids(spec):
            if _node_status(graph, nid) == NodeStatus.done:
                meta = _node_meta(graph, nid)
                output_preview = str(meta.get("result", ""))[:400]
                parts.append(f"[{nid}]\n{output_preview}")
        summary_input = "\n\n".join(parts)
        return self._llm(_SYSTEM_CONCLUDE, summary_input)


# ── 兼容性辅助（避免直接依赖内部 API）────────────────────────────────────────

def _all_node_ids(spec: Any) -> list[str]:
    if hasattr(spec, "all_node_ids"):
        return list(spec.all_node_ids())
    if hasattr(spec, "manifests"):
        return [m.task_id for m in spec.manifests]
    return []


def _node_status(graph: Any, node_id: str) -> NodeStatus | None:
    if hasattr(graph, "node_status"):
        return graph.node_status(node_id)
    return None


def _node_meta(graph: Any, node_id: str) -> dict:
    if hasattr(graph, "node_meta"):
        m = graph.node_meta(node_id)
        return m if isinstance(m, dict) else {}
    return {}


def _objective(spec: Any) -> str:
    if hasattr(spec, "objective"):
        return spec.objective
    if hasattr(spec, "title"):
        return spec.title
    return ""
