from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Generator

from agent.base import AgentBase, AgentResult
from plan.config import PlannerConfig
from plan.document import PlanDocument, PlanParser, PlanParseError, PlanValidator


_PLANNER_SYSTEM = """\
You are a planning agent. Your ONLY goal is to produce a valid execution plan in the specified Markdown format.

## Plan Markdown Format

```
# Plan: <concise title>

## Objective
<one or two sentences describing the goal>

## Tasks

### Module: <module name>
- [ ] **task_id** `profile:researcher` `max_steps:15` `depends_on:other_id`
  Task description (one line)
```

## Rules
1. task_id must be unique, snake_case (lowercase letters, digits, underscores only).
2. depends_on lists comma-separated task_ids that must complete before this task. No cycles.
3. profile choices: minimal | researcher | analyst | executor
4. parallel:true means the task can run alongside sibling tasks that have their deps satisfied.
5. Module names are visual groupings only; actual ordering is determined by depends_on.
6. Output ONLY the plan Markdown in your final answer — no prose before or after.
"""

_DRAFT_PROMPT = """\
Use scratchpad to:
1. Write a draft plan (key="plan_draft") listing all needed tasks with their dependencies.
2. Verify: are all depends_on references valid? Is there a cycle? Is the objective reachable?
3. Write the final corrected plan to scratchpad key="plan_final".
4. Finish with the final plan Markdown as your answer.
"""


class PlannerAgent(AgentBase):
    role = "planner"

    def __init__(self, cfg: PlannerConfig, llm_cfg_path: str) -> None:
        self._cfg = cfg
        self._llm_cfg_path = llm_cfg_path
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="planner")

    async def run(self, instruction: str, **ctx: Any) -> AgentResult:
        agent_id = str(uuid.uuid4())
        if self._cfg.mode == "interactive":
            raise RuntimeError(
                "PlannerAgent.run() is for auto mode. "
                "Use ConvPlanner for interactive mode."
            )
        doc = await asyncio.get_event_loop().run_in_executor(
            self._executor,
            self._run_auto_sync,
            instruction,
        )
        return AgentResult(agent_id=agent_id, role=self.role, status="done", output=doc)

    def _run_auto_sync(self, instruction: str) -> PlanDocument:
        from config.llm_core.config import LLMConfig
        from config.agent.tao_config import TaoConfig
        from config.agent.prompt_config import PromptConfig
        from config.agent.memory.memory_config import MemoryConfig
        from infra.llm import LLM
        from agent.react.action.manager import ToolManager
        from agent.react.tao import FinishEvent, TaoLoop

        llm = LLM(LLMConfig.from_yaml(self._llm_cfg_path))
        tool_manager = ToolManager()

        allowed_tools = list(self._cfg.tools or ["scratchpad"])
        if self._cfg.allow_search:
            allowed_tools += ["web_search", "knowledge_hybrid_search"]

        executor = tool_manager.build_executor()
        tool_descriptions = tool_manager.primary_descriptions(allowed_tools)

        memory = MemoryConfig()
        if not self._cfg.memory_long_term:
            memory.long_term.enabled = False
        if not self._cfg.memory_short_term:
            memory.short_term_enabled = False

        system_extra = _PLANNER_SYSTEM
        if self._cfg.system_prompt_extra:
            system_extra += f"\n\n{self._cfg.system_prompt_extra}"

        tao_cfg = TaoConfig(
            max_steps=self._cfg.max_steps,
            memory=memory,
            prompt=PromptConfig(system_note=system_extra),
        )
        tao = TaoLoop(
            llm=llm,
            executor=executor,
            tool_descriptions=tool_descriptions,
            cfg=tao_cfg,
        )

        full_prompt = f"{_DRAFT_PROMPT}\n\n## Goal\n{instruction}"
        validator = PlanValidator()

        for attempt in range(self._cfg.max_retries + 1):
            answer = ""
            for event in tao.stream(full_prompt):
                if isinstance(event, FinishEvent):
                    answer = event.answer

            try:
                doc = PlanParser.parse(answer)
            except PlanParseError as e:
                if attempt >= self._cfg.max_retries:
                    raise
                full_prompt = (
                    f"Your previous plan had a format error: {e}\n"
                    f"Please fix it and output a valid plan.\n\n"
                    f"Previous output:\n{answer}"
                )
                tao.reset()
                continue

            errors = validator.validate(doc)
            if errors:
                if attempt >= self._cfg.max_retries:
                    raise ValueError(f"Plan validation failed: {'; '.join(errors)}")
                full_prompt = (
                    f"Your plan has the following errors:\n"
                    + "\n".join(f"- {e}" for e in errors)
                    + f"\n\nPlease fix all errors and output a valid plan.\n\nPrevious plan:\n{answer}"
                )
                tao.reset()
                continue

            tao.post_process()
            return doc

        raise RuntimeError("Planner exhausted retries without producing a valid plan")


# ── ConvPlanner ───────────────────────────────────────────────────────────────

class ConvPlanner:
    """
    Interactive planning via multi-turn conversation (ConvLoop).
    The plan Markdown is kept in the scratchpad and refined across turns.
    When the user signals finalization, the latest draft is parsed and validated.
    """

    def __init__(self, cfg: PlannerConfig, llm_cfg_path: str) -> None:
        self._cfg = cfg
        self._llm_cfg_path = llm_cfg_path
        self._loop: Any | None = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="conv_planner")

    def _build_loop(self) -> Any:
        from config.llm_core.config import LLMConfig
        from config.agent.tao_config import TaoConfig
        from config.agent.prompt_config import PromptConfig
        from config.agent.memory.memory_config import MemoryConfig
        from infra.llm import LLM
        from agent.react.action.manager import ToolManager
        from agent.react.tao import TaoLoop
        from agent.react.loop import ConvLoop

        llm = LLM(LLMConfig.from_yaml(self._llm_cfg_path))
        tool_manager = ToolManager()

        allowed_tools = list(self._cfg.tools or ["scratchpad"])
        if self._cfg.allow_search:
            allowed_tools += ["web_search", "knowledge_hybrid_search"]

        executor = tool_manager.build_executor()
        tool_descriptions = tool_manager.primary_descriptions(allowed_tools)

        memory = MemoryConfig()
        if not self._cfg.memory_long_term:
            memory.long_term.enabled = False

        system_extra = (
            _PLANNER_SYSTEM
            + "\n\nYou are in interactive planning mode. Collaborate with the user to refine the plan. "
            "After each message, update the plan in scratchpad key='plan_draft'. "
            "When the user is satisfied, output the final plan Markdown as your answer."
        )
        if self._cfg.system_prompt_extra:
            system_extra += f"\n\n{self._cfg.system_prompt_extra}"

        tao_cfg = TaoConfig(
            max_steps=self._cfg.max_steps,
            memory=memory,
            prompt=PromptConfig(system_note=system_extra),
        )
        tao = TaoLoop(
            llm=llm,
            executor=executor,
            tool_descriptions=tool_descriptions,
            cfg=tao_cfg,
        )
        return ConvLoop(tao)

    @property
    def loop(self) -> Any:
        if self._loop is None:
            self._loop = self._build_loop()
        return self._loop

    async def chat(self, message: str) -> tuple[str, PlanDocument | None]:
        response_text, finalize = await asyncio.get_event_loop().run_in_executor(
            self._executor,
            self._chat_sync,
            message,
        )
        if finalize:
            doc = self._extract_and_validate(response_text)
            return response_text, doc
        return response_text, None

    def _chat_sync(self, message: str) -> tuple[str, bool]:
        from agent.react.tao import FinishEvent

        answer = ""
        for event in self.loop.stream(message):
            if isinstance(event, FinishEvent):
                answer = event.answer

        finalize = self._detect_finalize(message, answer)
        return answer, finalize

    def _detect_finalize(self, user_msg: str, response: str) -> bool:
        msg_lower = user_msg.lower()
        for kw in self._cfg.finalize_keywords:
            if kw.lower() in msg_lower:
                return True
        return False

    def _extract_and_validate(self, response_text: str) -> PlanDocument:
        validator = PlanValidator()
        try:
            doc = PlanParser.parse(response_text)
        except PlanParseError as e:
            raise ValueError(f"Plan finalization failed — format error: {e}") from e
        errors = validator.validate(doc)
        if errors:
            raise ValueError(
                f"Plan finalization failed — validation errors:\n" + "\n".join(f"- {e}" for e in errors)
            )
        return doc

    def reset(self) -> None:
        if self._loop is not None:
            self._loop.reset()
