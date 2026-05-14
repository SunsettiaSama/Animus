"""原子规划层实现：AtomicPlanner。

设计原则
--------
本模块位于 base/components/，不依赖任何 flow/ 层具体实现（无 _build_tao_loop、
无 PlannerConfig、无 TaoLoop 直接导入）。LLM 调用能力通过 LlmCallFn 注入，
由 base/defaults.py（接线层）负责将 flow/ 的 TaoLoop 包装为合规的 LlmCallFn。
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


# ── System prompt ─────────────────────────────────────────────────────────────

_ATOMIC_SYSTEM = """\
You are an Atomic Planner. Your job is to assess a single task node and decide
whether it is already atomic (small enough to execute directly) or needs to be
decomposed into sub-nodes.

## Definitions

**atomic**: The node has a clear, single responsibility. Its input and output
can be expressed in one sentence each, and it can be completed in at most
{max_atom_steps} TAO steps. A single LLM call or script can accomplish it.

**flat**: The node should be expanded into {max_width} or fewer parallel/sequential
sibling nodes at the SAME level of the DAG. Use this when sub-tasks are
independent and need to be coordinated with OTHER nodes outside this task.

**nested**: The node is a self-contained subsystem. Decompose it into a private
sub-graph. Use this when sub-tasks are tightly coupled INTERNALLY and the node
presents a clean interface to the outside world.

## Output Format (JSON only, no prose)

```json
{{
  "kind": "atomic" | "flat" | "nested",
  "reason": "<one sentence explaining the decision>",
  "output_node_id": "<task_id of the exit node, only for nested; empty string otherwise>",
  "sub_nodes": [
    {{
      "task_id": "<snake_case_id>",
      "description": "<clear single-responsibility description>",
      "depends_on": ["<task_id>", ...],
      "input_contract": "<what this node needs as input>",
      "output_contract": "<what this node produces>",
      "tool_package": "<package name or null>",
      "max_steps": <integer or null>
    }},
    ...
  ]
}}
```

For `atomic`, `sub_nodes` must be an empty list.
All `task_id` values must be unique snake_case strings.
The `depends_on` list may only reference other task_ids in `sub_nodes`.
"""

_ASSESS_PROMPT = """\
Assess the following node and return a JSON topology decision.

Node to assess:
  task_id:         {task_id}
  description:     {description}
  input_contract:  {input_contract}
  output_contract: {output_contract}
  tool_package:    {tool_package}
  max_steps:       {max_steps}

Budget constraints:
  max_depth remaining: {max_depth}
  max_width:           {max_width}
  max_atom_steps:      {max_atom_steps}

{context_block}
Return ONLY the JSON object described in the system prompt.
"""


# ── Parser ────────────────────────────────────────────────────────────────────

def _parse_decision(raw: str, original: NodeManifest) -> TopologyDecision:
    """Parse LLM JSON output into a TopologyDecision."""
    start = raw.find("{")
    end = raw.rfind("}") + 1
    data = json.loads(raw[start:end])

    kind = TopologyKind(data["kind"])
    reason: str = data.get("reason", "")
    output_node_id: str = data.get("output_node_id", "")

    sub_manifests: tuple[NodeManifest, ...] = ()
    if kind != TopologyKind.atomic:
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


# ── AtomicPlanner ─────────────────────────────────────────────────────────────

class AtomicPlanner:
    """原子规划层的具体实现：通过注入的 LlmCallFn 对节点做拓扑决策。

    执行流程
    --------
    1. 先通过 is_atomic()（确定性判断）快速过滤：满足则直接返回 atomic 决策。
    2. 在线程池中调用 _assess_sync：通过 llm_call 获取 LLM 答案并解析。
    3. 若 reviewer 已注入且 budget.review_enabled，调用 reviewer.review() 审查：
       - approved=True    → 使用原决策。
       - approved=False，revised 非 None → 使用修订版决策。
       - approved=False，revised=None    → 降级为 atomic。
    4. 解析失败则降级为 atomic（保守策略，避免卡住流程）。

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
        import asyncio, functools

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

        # ── 审查阶段（双循环咨询层）───────────────────────────────────────────
        if self._reviewer is not None and budget.review_enabled:
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

    def _assess_sync(
        self,
        manifest: NodeManifest,
        budget: DecompositionBudget,
        context: dict | None,
    ) -> TopologyDecision:
        system = _ATOMIC_SYSTEM.format(
            max_atom_steps=budget.max_atom_steps,
            max_width=budget.max_width,
        )

        context_block = ""
        if context:
            lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
            context_block = f"Additional context:\n{lines}\n"

        prompt = _ASSESS_PROMPT.format(
            task_id=manifest.task_id,
            description=manifest.description,
            input_contract=manifest.input_contract or "(not specified)",
            output_contract=manifest.output_contract or "(not specified)",
            tool_package=manifest.tool_package or "null",
            max_steps=manifest.max_steps or "null",
            max_depth=budget.max_depth,
            max_width=budget.max_width,
            max_atom_steps=budget.max_atom_steps,
            context_block=context_block,
        )

        answer = self._llm_call(system, prompt)
        decision = _parse_decision(answer, manifest)

        # Enforce budget width constraint
        if len(decision.sub_manifests) > budget.max_width:
            return TopologyDecision(
                kind=TopologyKind.nested,
                reason=f"sub_nodes ({len(decision.sub_manifests)}) exceeded max_width "
                       f"({budget.max_width}), promoted to nested",
                sub_manifests=decision.sub_manifests,
                output_node_id=decision.output_node_id
                    or (decision.sub_manifests[-1].task_id if decision.sub_manifests else ""),
            )

        return decision
