"""原子规划审查层实现：AtomicReviewer。

设计原则
--------
同 atomic_planner.py：无 flow/ 依赖，LLM 调用通过注入的 LlmCallFn 完成。
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor

from agent.flow.base.budget import DecompositionBudget, TopologyKind
from agent.flow.base.components.atomic_planner import LlmCallFn
from agent.flow.base.components.node_spec import (
    NodeManifest,
    ReviewOutcome,
    TopologyDecision,
)
from agent.flow.base.components.observation import ObservationMode


# ── System prompt ─────────────────────────────────────────────────────────────

_REVIEWER_SYSTEM = """\
You are an Atomic Reviewer. Your job is to audit a topology decision produced by
an Atomic Planner and verify that it is self-consistent and correct.

## What to check

1. **I/O chain closure**: For each sequential edge A → B in sub_nodes, verify that
   A.output_contract can plausibly satisfy B.input_contract. Report any mismatch.

2. **Dependency correctness**: Check that all task_ids in `depends_on` lists exist
   in sub_nodes and that the graph is acyclic.

3. **Kind appropriateness**:
   - `flat` should only be used when sub-tasks need to be coordinated with OTHER
     nodes outside this task. If sub-tasks are tightly coupled internally, prefer `nested`.
   - `nested` requires a non-empty `output_node_id` pointing to the exit node.
   - `atomic` must have empty sub_nodes.

4. **Width constraint**: sub_nodes count must not exceed {max_width}.

5. **Decomposition value**: The split must reduce complexity meaningfully — not just
   rename the parent task or produce a single child that is identical to the parent.

## Output Format (JSON only, no prose)

```json
{{
  "approved": true | false,
  "critique": "<empty string if approved; otherwise a concise explanation>",
  "revised": null | {{
    "kind": "atomic" | "flat" | "nested",
    "reason": "<revised reason>",
    "output_node_id": "<exit node task_id or empty string>",
    "sub_nodes": [ {{ ...same schema as AtomicPlanner... }} ]
  }}
}}
```

If `approved` is true, `revised` MUST be null.
If `approved` is false and you cannot produce a valid revision, set `revised` to null
(the orchestrator will fall back to atomic).
"""

_REVIEW_PROMPT = """\
Review the following topology decision for the node described below.

## Original node
  task_id:         {task_id}
  description:     {description}
  input_contract:  {input_contract}
  output_contract: {output_contract}
  tool_package:    {tool_package}
  max_steps:       {max_steps}

## Proposed topology decision
  kind:            {kind}
  reason:          {reason}
  output_node_id:  {output_node_id}
  sub_nodes:
{sub_nodes_block}

## Budget constraints
  max_width:           {max_width}
  max_review_rounds:   {max_review_rounds}

{context_block}
Return ONLY the JSON object described in the system prompt.
"""


# ── Parser ────────────────────────────────────────────────────────────────────

def _parse_outcome(raw: str, decision: TopologyDecision) -> ReviewOutcome:
    """Parse LLM JSON into a ReviewOutcome, falling back to approved=True on error."""
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return ReviewOutcome(approved=True, critique="(reviewer returned unparseable output)")

    data = json.loads(raw[start:end])
    approved: bool = bool(data.get("approved", True))
    critique: str  = data.get("critique", "")

    if approved:
        return ReviewOutcome(approved=True)

    raw_revised = data.get("revised")
    if raw_revised is None:
        return ReviewOutcome(approved=False, critique=critique, revised=None)

    kind = TopologyKind(raw_revised["kind"])
    sub_manifests: tuple[NodeManifest, ...] = ()
    if kind != TopologyKind.atomic:
        nodes = []
        for n in raw_revised.get("sub_nodes", []):
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

    revised = TopologyDecision(
        kind=kind,
        reason=raw_revised.get("reason", critique),
        sub_manifests=sub_manifests,
        output_node_id=raw_revised.get("output_node_id", ""),
    )
    return ReviewOutcome(approved=False, critique=critique, revised=revised)


def _fmt_sub_nodes(decision: TopologyDecision) -> str:
    if not decision.sub_manifests:
        return "    (none)"
    lines = []
    for m in decision.sub_manifests:
        lines.append(
            f"    - {m.task_id}: {m.description!r}\n"
            f"      depends_on={list(m.depends_on)}\n"
            f"      input={m.input_contract!r}  output={m.output_contract!r}"
        )
    return "\n".join(lines)


# ── AtomicReviewer ────────────────────────────────────────────────────────────

class AtomicReviewer:
    """对 AtomicPlanner 给出的 TopologyDecision 做一次自洽性审查。

    审查流程
    --------
    1. 如果 budget.review_enabled 为 False，直接返回 approved。
    2. 在线程池中调用 _review_sync：通过 llm_call 获取答案并解析。
    3. 解析 JSON 输出为 ReviewOutcome：
       - approved=True  → 直接返回。
       - approved=False，revised 非 None → 返回修订版。
       - approved=False，revised=None    → 返回 approved=False（调用方降级为 atomic）。
    4. 任何解析/调用异常 → 保守地返回 approved=True（不打断流程）。

    注入约定
    --------
    llm_call: LlmCallFn — (system_prompt, user_prompt) -> answer_string。
    """

    def __init__(
        self,
        llm_call: LlmCallFn,
        executor_pool: ThreadPoolExecutor | None = None,
    ) -> None:
        self._llm_call = llm_call
        self._owned_pool = executor_pool is None
        self._executor = executor_pool or ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="atomic_reviewer"
        )

    async def review(
        self,
        manifest: NodeManifest,
        decision: TopologyDecision,
        budget: DecompositionBudget,
        *,
        context: dict | None = None,
    ) -> ReviewOutcome:
        import asyncio, functools

        if not budget.review_enabled:
            return ReviewOutcome(approved=True, critique="review disabled by budget")

        outcome = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            functools.partial(self._review_sync, manifest, decision, budget, context),
        )
        return outcome

    def _review_sync(
        self,
        manifest: NodeManifest,
        decision: TopologyDecision,
        budget: DecompositionBudget,
        context: dict | None,
    ) -> ReviewOutcome:
        system = _REVIEWER_SYSTEM.format(max_width=budget.max_width)

        context_block = ""
        if context:
            lines = "\n".join(f"  {k}: {v}" for k, v in context.items())
            context_block = f"Additional context:\n{lines}\n"

        prompt = _REVIEW_PROMPT.format(
            task_id=manifest.task_id,
            description=manifest.description,
            input_contract=manifest.input_contract or "(not specified)",
            output_contract=manifest.output_contract or "(not specified)",
            tool_package=manifest.tool_package or "null",
            max_steps=manifest.max_steps or "null",
            kind=decision.kind.value,
            reason=decision.reason,
            output_node_id=decision.output_node_id or "(none)",
            sub_nodes_block=_fmt_sub_nodes(decision),
            max_width=budget.max_width,
            max_review_rounds=budget.max_review_rounds,
            context_block=context_block,
        )

        answer = self._llm_call(system, prompt)
        return _parse_outcome(answer, decision)
