"""原子规划层实现：AtomicPlanner（两阶段调用）。

设计原则
--------
本模块位于 base/components/，不依赖任何 flow/ 层具体实现（无 _build_tao_loop、
无 PlannerConfig、无 TaoLoop 直接导入）。LLM 调用能力通过 LlmCallFn 注入，
由 base/defaults.py（接线层）负责将 flow/ 的 TaoLoop 包装为合规的 LlmCallFn。

两阶段架构
----------
原始实现将「拓扑决策」与「子节点生成」合并在一次 LLM 调用中，造成两个问题：
1. 提示词同时携带 9 个字段（node + budget），许多字段为空时增加无效噪声。
2. LLM 需同时决策 kind 并生成完整 sub_manifests（含 I/O contract），认知负担重，
   容易产生结构混乱的输出。

拆分后的流程：
  Phase 1 — Topology Vote（轻量调用）
    输入：description + budget（3 个约束）
    输出：{"kind": ..., "reason": ...}
    目标：仅决定是否要拆分以及拆分类型

  Phase 2 — Sub-manifest Generation（仅 flat/nested 触发）
    输入：原始 manifest 所有字段 + topology vote 的决定 + budget
    输出：{"output_node_id": ..., "sub_nodes": [...]}
    目标：专注生成结构正确、I/O 闭合的子节点列表

审查层（AtomicReviewer）在 Phase 2 之后运行，只审查完整 TopologyDecision。
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TYPE_CHECKING

from agent.flow.base.budget import DecompositionBudget, TopologyKind, is_atomic
from agent.flow.base.components.node_spec import NodeManifest, ReviewOutcome, TopologyDecision
from agent.flow.base.components.observation import ObservationMode

if TYPE_CHECKING:
    from agent.flow.base.components.atomic_reviewer import AtomicReviewer

# ── LLM 调用抽象 ──────────────────────────────────────────────────────────────

# (system_prompt, user_prompt) -> answer_string
LlmCallFn = Callable[[str, str], str]


# ── Phase 1：Topology Vote ─────────────────────────────────────────────────────

_VOTE_SYSTEM = """\
You are a task topology classifier. Given a single task description and budget
constraints, decide the topology kind.

## Topology Kinds

**atomic**: The task has ONE clear responsibility and can be completed by a
single agent in at most {max_atom_steps} steps without sub-delegation.

**flat**: The task should expand into {max_width} or fewer sibling nodes at the
SAME DAG level. Use when sub-tasks need coordination with nodes OUTSIDE this task.

**nested**: The task is a self-contained subsystem. Use when sub-tasks are
tightly coupled INTERNALLY and the task presents a clean input/output interface.

## Output (JSON only, no prose)

```json
{{"kind": "atomic" | "flat" | "nested", "reason": "<one sentence>"}}
```
"""

_VOTE_PROMPT = """\
Task:
  id:          {task_id}
  description: {description}
{optional_io}
Budget:
  depth remaining: {max_depth}
  max_width:       {max_width}
  max_atom_steps:  {max_atom_steps}
{context_block}
Return ONLY the JSON object.
"""


# ── Phase 2：Sub-manifest Generation ──────────────────────────────────────────

_DECOMPOSE_SYSTEM = """\
You are a task decomposer. Given a task node and the already-decided topology
kind ({kind}), generate the sub-nodes.

## Rules
- All task_id values: unique snake_case strings.
- depends_on: may only reference task_ids within sub_nodes.
- Each sub-node must have a SINGLE clear responsibility.
- Maximum sub_nodes count: {max_width}.
- For `nested`: set output_node_id to the task_id of the exit (final) sub-node.
- For `flat`:   output_node_id should be empty string.

## Output (JSON only, no prose)

```json
{{
  "output_node_id": "<exit node task_id or empty string>",
  "sub_nodes": [
    {{
      "task_id": "<snake_case_id>",
      "description": "<single-responsibility description>",
      "depends_on": ["<task_id>", ...],
      "input_contract": "<what this sub-node needs>",
      "output_contract": "<what this sub-node produces>",
      "tool_package": "<package name or null>",
      "max_steps": <integer or null>
    }}
  ]
}}
```
"""

_DECOMPOSE_PROMPT = """\
Parent node to decompose:
  task_id:         {task_id}
  description:     {description}
{optional_io}  topology:        {kind}
  topology_reason: {reason}
{optional_pkg}
Budget:
  max_width:       {max_width}
{context_block}
Return ONLY the JSON object.
"""


# ── Parsers ────────────────────────────────────────────────────────────────────

def _parse_vote(raw: str) -> tuple[TopologyKind, str]:
    """Parse Phase-1 JSON → (kind, reason). Falls back to atomic on error."""
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return TopologyKind.atomic, "(vote parse error, forced atomic)"
    data = json.loads(raw[start:end])
    kind = TopologyKind(data.get("kind", "atomic"))
    reason = data.get("reason", "")
    return kind, reason


def _parse_sub_manifests(raw: str) -> tuple[tuple[NodeManifest, ...], str]:
    """Parse Phase-2 JSON → (sub_manifests, output_node_id). Returns empty on error."""
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return (), ""
    data = json.loads(raw[start:end])
    output_node_id: str = data.get("output_node_id", "")
    nodes = []
    for n in data.get("sub_nodes", []):
        nodes.append(NodeManifest(
            task_id=n["task_id"],
            description=n["description"],
            depends_on=tuple(n.get("depends_on", [])),
            input_contract=n.get("input_contract", ""),
            output_contract=n.get("output_contract", ""),
            tool_package=n.get("tool_package") or None,
            max_steps=n.get("max_steps") or None,
            observation_mode=ObservationMode.distilled,
        ))
    return tuple(nodes), output_node_id


def _parse_decision(raw: str, manifest: NodeManifest) -> TopologyDecision:
    """Unified parser: raw LLM JSON → TopologyDecision.

    Accepts a single JSON object that contains both the topology vote fields
    (``kind``, ``reason``) and the optional sub-manifest fields
    (``sub_nodes``, ``output_node_id``).  Any surrounding prose is stripped
    before parsing.  Falls back to *atomic* on any parse error.

    This mirrors the two-phase internal parsers (_parse_vote / _parse_sub_manifests)
    but operates on a single JSON blob — useful for single-call prompts,
    testing, and external callers that build the JSON themselves.
    """
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return TopologyDecision(
            kind=TopologyKind.atomic,
            reason="(decision parse error, forced atomic)",
        )
    data: dict = json.loads(raw[start:end])
    kind = TopologyKind(data.get("kind", "atomic"))
    reason: str = data.get("reason", "")
    output_node_id: str = data.get("output_node_id", "")
    sub_manifests: tuple[NodeManifest, ...] = ()
    if kind is not TopologyKind.atomic:
        nodes = []
        for n in data.get("sub_nodes", []):
            nodes.append(NodeManifest(
                task_id=n["task_id"],
                description=n["description"],
                depends_on=tuple(n.get("depends_on", [])),
                input_contract=n.get("input_contract", ""),
                output_contract=n.get("output_contract", ""),
                tool_package=n.get("tool_package") or None,
                max_steps=n.get("max_steps") or None,
                observation_mode=ObservationMode.distilled,
            ))
        sub_manifests = tuple(nodes)
    return TopologyDecision(
        kind=kind,
        reason=reason,
        sub_manifests=sub_manifests,
        output_node_id=output_node_id,
    )


def _optional_io(manifest: NodeManifest) -> str:
    """只在 I/O contract 已填写时加入提示，避免空字段噪声。"""
    lines = []
    if manifest.input_contract.strip():
        lines.append(f"  input_contract:  {manifest.input_contract}")
    if manifest.output_contract.strip():
        lines.append(f"  output_contract: {manifest.output_contract}")
    return ("\n".join(lines) + "\n") if lines else ""


def _optional_pkg(manifest: NodeManifest) -> str:
    if manifest.tool_package:
        return f"  tool_package:    {manifest.tool_package}\n"
    if manifest.max_steps is not None:
        return f"  max_steps:       {manifest.max_steps}\n"
    return ""


# ── AtomicPlanner ─────────────────────────────────────────────────────────────

class AtomicPlanner:
    """原子规划层的具体实现：两阶段 LLM 调用决定节点拓扑。

    执行流程
    --------
    1. is_atomic()（确定性快速路径，无 LLM）→ 满足则直接返回 atomic。
    2. Phase 1 – Topology Vote（轻量 LLM 调用）
       仅携带 description + budget 约束，决定 atomic / flat / nested。
       → 若 atomic，直接返回，**不触发 Phase 2**。
    3. Phase 2 – Sub-manifest Generation（仅 flat / nested）
       携带完整 manifest 上下文 + Phase-1 决策结果，
       专注生成结构正确、I/O 闭合的子节点列表。
    4. AtomicReviewer 审查（budget.review_enabled = True）
       → approved → 使用原决策
       → rejected, revised → 使用修订版
       → rejected, no revision → 降级 atomic
    5. 任何解析失败均保守降级为 atomic。

    注入约定
    --------
    llm_call: LlmCallFn — (system_prompt, user_prompt) -> answer_string。
    由 base/defaults.py 的 _build_llm_call() 包装 TaoLoop 提供。
    """

    def __init__(
        self,
        llm_call: LlmCallFn,
        executor_pool: ThreadPoolExecutor | None = None,
        reviewer: "AtomicReviewer | None" = None,
    ) -> None:
        self._llm_call = llm_call
        self._owned_pool = executor_pool is None
        self._executor = executor_pool or ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="atomic_planner"
        )
        self._reviewer = reviewer

    def set_reviewer(self, reviewer: "AtomicReviewer") -> None:
        """运行时注入 reviewer（registry 延迟装配时使用）。"""
        self._reviewer = reviewer

    async def assess(
        self,
        manifest: NodeManifest,
        budget: DecompositionBudget,
        *,
        context: dict | None = None,
    ) -> TopologyDecision:
        import asyncio
        import functools

        if is_atomic(manifest, budget):
            return TopologyDecision(
                kind=TopologyKind.atomic,
                reason="passed is_atomic() deterministic check",
            )

        if budget.exhausted:
            return TopologyDecision(
                kind=TopologyKind.atomic,
                reason="decomposition budget exhausted, forced atomic",
            )

        decision = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            functools.partial(self._assess_sync, manifest, budget, context),
        )

        # ── 审查阶段（只审查 flat / nested 决策）────────────────────────────
        if (
            self._reviewer is not None
            and budget.review_enabled
            and decision.kind != TopologyKind.atomic
        ):
            outcome: ReviewOutcome = await self._reviewer.review(
                manifest, decision, budget, context=context
            )
            if not outcome.approved:
                if outcome.revised is not None:
                    decision = outcome.revised
                else:
                    decision = TopologyDecision(
                        kind=TopologyKind.atomic,
                        reason=f"reviewer rejected decomposition, fallback atomic: {outcome.critique}",
                    )

        return decision

    # ── Phase 1 ───────────────────────────────────────────────────────────────

    def _vote_sync(
        self,
        manifest: NodeManifest,
        budget: DecompositionBudget,
        context: dict | None,
    ) -> tuple[TopologyKind, str]:
        """轻量调用：只决定 atomic / flat / nested，不生成 sub_manifests。"""
        system = _VOTE_SYSTEM.format(
            max_atom_steps=budget.max_atom_steps,
            max_width=budget.max_width,
        )
        context_block = ""
        if context:
            ctx_lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
            context_block = f"Additional context:\n{ctx_lines}\n"

        prompt = _VOTE_PROMPT.format(
            task_id=manifest.task_id,
            description=manifest.description,
            optional_io=_optional_io(manifest),
            max_depth=budget.max_depth,
            max_width=budget.max_width,
            max_atom_steps=budget.max_atom_steps,
            context_block=context_block,
        )
        answer = self._llm_call(system, prompt)
        return _parse_vote(answer)

    # ── Phase 2 ───────────────────────────────────────────────────────────────

    def _decompose_sync(
        self,
        manifest: NodeManifest,
        kind: TopologyKind,
        reason: str,
        budget: DecompositionBudget,
        context: dict | None,
    ) -> tuple[tuple[NodeManifest, ...], str]:
        """专注生成子节点列表，不重复决策 kind。"""
        system = _DECOMPOSE_SYSTEM.format(
            kind=kind.value,
            max_width=budget.max_width,
        )
        context_block = ""
        if context:
            ctx_lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
            context_block = f"Additional context:\n{ctx_lines}\n"

        prompt = _DECOMPOSE_PROMPT.format(
            task_id=manifest.task_id,
            description=manifest.description,
            optional_io=_optional_io(manifest),
            kind=kind.value,
            reason=reason,
            optional_pkg=_optional_pkg(manifest),
            max_width=budget.max_width,
            context_block=context_block,
        )
        answer = self._llm_call(system, prompt)
        return _parse_sub_manifests(answer)

    # ── Combined sync entry point ──────────────────────────────────────────────

    def _assess_sync(
        self,
        manifest: NodeManifest,
        budget: DecompositionBudget,
        context: dict | None,
    ) -> TopologyDecision:
        # Phase 1
        kind, reason = self._vote_sync(manifest, budget, context)

        if kind == TopologyKind.atomic:
            return TopologyDecision(kind=TopologyKind.atomic, reason=reason)

        # Phase 2
        sub_manifests, output_node_id = self._decompose_sync(
            manifest, kind, reason, budget, context
        )

        # 子节点为空时安全降级
        if not sub_manifests:
            return TopologyDecision(
                kind=TopologyKind.atomic,
                reason=f"decompose returned no sub_nodes, fallback atomic (original: {reason})",
            )

        # 超宽时强制提升为 nested
        if len(sub_manifests) > budget.max_width:
            kind = TopologyKind.nested
            reason = (
                f"sub_nodes ({len(sub_manifests)}) exceeded max_width "
                f"({budget.max_width}), promoted to nested"
            )
            output_node_id = output_node_id or sub_manifests[-1].task_id

        return TopologyDecision(
            kind=kind,
            reason=reason,
            sub_manifests=sub_manifests,
            output_node_id=output_node_id,
        )
