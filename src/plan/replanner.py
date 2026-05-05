from __future__ import annotations

import asyncio
import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from agent.base import AgentBase, AgentResult
from plan.config import ReplannerConfig
from plan.document import PlanDocument, PlanTask, TaskStatus
from plan.patch import HumanPatch, PatchOp


# ── ReplanDecision ────────────────────────────────────────────────────────────

@dataclass
class ReplanDecision:
    decision: str                    # done | continue | modify | abort
    trigger: str = ""
    confidence: float = 1.0
    reason: str = ""
    patches: list[HumanPatch] = field(default_factory=list)
    conclusion: str = ""


# ── ReplannerInputBuilder ─────────────────────────────────────────────────────

class ReplannerInputBuilder:
    def __init__(self, cfg: ReplannerConfig) -> None:
        self._cfg = cfg

    def build(self, doc: PlanDocument, trigger: str, cycle: int) -> str:
        parts: list[str] = []

        # Objective
        parts.append("=== Objective ===")
        parts.append(doc.objective)

        # Completed tasks
        done_tasks = [t for t in doc.all_tasks() if t.status == TaskStatus.done]
        if done_tasks:
            parts.append("\n=== Completed Tasks (Summaries) ===")
            for t in done_tasks:
                ctx = t.execution_ctx
                steps = f"({ctx.step_count} steps)" if ctx else ""
                summary = ""
                if t.result:
                    summary = t.result[:self._cfg.result_summary_max_chars]
                elif ctx and ctx.result_summary:
                    summary = ctx.result_summary[:self._cfg.result_summary_max_chars]
                parts.append(f"✓ {t.task_id} {steps}: {summary}")

        # Failed tasks with detailed context
        failed_tasks = [t for t in doc.all_tasks() if t.status == TaskStatus.failed]
        if failed_tasks:
            parts.append("\n=== Failed Tasks (Detailed Context) ===")
            for t in failed_tasks:
                ctx = t.execution_ctx
                retries = f" after {ctx.retry_count} retries" if ctx else ""
                error = t.error or (ctx.error if ctx else "unknown error")
                parts.append(f"✗ {t.task_id}: {error}{retries}")
                if ctx and ctx.last_steps:
                    n = self._cfg.failed_last_steps
                    for step in ctx.last_steps[-n:]:
                        parts.append(f"    {step}")

        # Remaining plan
        pending_tasks = [
            t for t in doc.all_tasks()
            if t.status in (TaskStatus.pending, TaskStatus.paused)
        ]
        if pending_tasks:
            parts.append("\n=== Remaining Plan ===")
            for mod in doc.modules:
                mod_pending = [t for t in mod.tasks if t in pending_tasks]
                if mod_pending:
                    parts.append(f"### Module: {mod.name}")
                    for t in mod_pending:
                        deps = f" depends_on:{','.join(t.depends_on)}" if t.depends_on else ""
                        parts.append(f"- [ ] **{t.task_id}** profile:{t.profile}{deps}")
                        parts.append(f"  {t.description}")

        # Trigger info
        parts.append(f"\n=== Trigger ===")
        parts.append(f"{trigger} | cycle: {cycle}")

        return "\n".join(parts)


# ── System prompt ─────────────────────────────────────────────────────────────

_REPLANNER_SYSTEM = """\
You are a replanning agent. Analyse the current plan execution state and decide what to do next.

Your response MUST be valid JSON matching this schema:
{
  "decision": "done | continue | modify | abort",
  "trigger": "<trigger that called you>",
  "confidence": 0.0-1.0,
  "reason": "<brief explanation>",
  "patches": [
    {"op": "skip", "task_id": "..."},
    {"op": "set_params", "task_id": "...", "profile": "analyst"},
    {"op": "add_task", "task_id": "new_task", "module": "...", "profile": "minimal",
     "description": "...", "depends_on": ["existing_id"]}
  ],
  "conclusion": "<final answer if decision=done>"
}

Decisions:
- done: All objectives are met. Provide conclusion.
- continue: Plan is on track, no changes needed.
- modify: Apply patches to fix/adjust pending tasks.
- abort: Irrecoverable failure. Provide best current answer in conclusion.

Respond with ONLY the JSON object, no other text.
"""


# ── ReplannerAgent ────────────────────────────────────────────────────────────

class ReplannerAgent(AgentBase):
    role = "replanner"

    def __init__(self, cfg: ReplannerConfig, llm_cfg_path: str) -> None:
        self._cfg = cfg
        self._llm_cfg_path = llm_cfg_path
        self._builder = ReplannerInputBuilder(cfg)
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="replanner")

    async def run(self, instruction: str, **ctx: Any) -> AgentResult:
        doc: PlanDocument = ctx["doc"]
        trigger: str = ctx.get("trigger", "manual")
        cycle: int = ctx.get("cycle", 0)

        agent_id = str(uuid.uuid4())
        decision = await asyncio.get_event_loop().run_in_executor(
            self._executor,
            self._replan_sync,
            doc,
            trigger,
            cycle,
        )
        return AgentResult(agent_id=agent_id, role=self.role, status="done", output=decision)

    def _replan_sync(self, doc: PlanDocument, trigger: str, cycle: int) -> ReplanDecision:
        from langchain_core.messages import HumanMessage, SystemMessage
        from config.llm_core.config import LLMConfig
        from llm_core.llm import LLM

        llm = LLM(LLMConfig.from_yaml(self._llm_cfg_path))
        context = self._builder.build(doc, trigger, cycle)

        messages = [
            SystemMessage(content=_REPLANNER_SYSTEM),
            HumanMessage(content=context),
        ]
        response = llm.generate_messages(messages)

        return self._parse_decision(response, trigger)

    def _parse_decision(self, text: str, trigger: str) -> ReplanDecision:
        # Strip markdown code fences if present
        text = text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                l for l in lines if not l.startswith("```")
            ).strip()

        raw: dict = {}
        try:
            raw = json.loads(text)
        except json.JSONDecodeError:
            # Fallback: return continue if parsing fails
            return ReplanDecision(
                decision="continue",
                trigger=trigger,
                reason=f"Could not parse replanner response: {text[:200]}",
            )

        patches: list[HumanPatch] = []
        for p in raw.get("patches", []):
            op_str = p.get("op", "")
            task_id = p.get("task_id")
            payload = {k: v for k, v in p.items() if k not in ("op", "task_id")}
            try:
                patches.append(HumanPatch(op=PatchOp(op_str), task_id=task_id, payload=payload))
            except ValueError:
                pass  # Unknown op — skip

        return ReplanDecision(
            decision=raw.get("decision", "continue"),
            trigger=raw.get("trigger", trigger),
            confidence=float(raw.get("confidence", 1.0)),
            reason=raw.get("reason", ""),
            patches=patches,
            conclusion=raw.get("conclusion", ""),
        )

    def should_trigger(self, trigger: str) -> bool:
        return trigger in self._cfg.triggers
