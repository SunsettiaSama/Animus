from __future__ import annotations

import asyncio
import dataclasses
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agent.base import AgentBase, AgentResult
from agent.flow.document import PlanDocument, PlanTask, TaskExecutionContext, TaskStatus


class ExecutorAgent(AgentBase):
    role = "executor"

    def __init__(
        self,
        llm_cfg_path: str,
        agent_cfg: Any = None,
        executor_pool: ThreadPoolExecutor | None = None,
    ) -> None:
        self._llm_cfg_path = llm_cfg_path
        self._agent_cfg = agent_cfg
        self._owned_pool = executor_pool is None
        self._executor = executor_pool or ThreadPoolExecutor(
            max_workers=8, thread_name_prefix="executor"
        )

    async def run(self, instruction: str, **ctx: Any) -> AgentResult:
        task: PlanTask = ctx["task"]
        doc: PlanDocument = ctx["doc"]
        step_callback = ctx.get("step_callback")

        agent_id = str(uuid.uuid4())
        await doc.update_task(task.task_id, status=TaskStatus.running)

        profile_name = task.params.get("profile", task.profile)
        max_steps = task.params.get("max_steps", task.max_steps)

        result = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            self._run_sync,
            instruction,
            profile_name,
            max_steps,
            step_callback,
        )
        answer = result.get("answer", "")
        step_count = result.get("step_count", 0)
        steps_log = result.get("steps_log", [])

        exec_ctx = TaskExecutionContext(
            task_id=task.task_id,
            status="done",
            result_summary=answer[:300] if answer else "",
            step_count=step_count,
            last_steps=steps_log[-3:],
            retry_count=ctx.get("retry_count", 0),
        )
        await doc.update_task(
            task.task_id,
            status=TaskStatus.done,
            result=answer,
            execution_ctx=exec_ctx,
        )
        return AgentResult(
            agent_id=agent_id,
            role=self.role,
            status="done",
            output=answer,
            execution_ctx=exec_ctx,
        )

    def _run_sync(
        self,
        instruction: str,
        profile_name: str,
        max_steps: int | None,
        step_callback=None,
    ) -> dict:
        from agent.profile import SubAgentConfig, SubAgentProfile
        from agent.runner import SubAgentRunner

        agent_cfg: SubAgentConfig = self._agent_cfg or SubAgentConfig()

        profile_obj = (
            agent_cfg.profiles.get(profile_name)
            or agent_cfg.profiles.get("minimal")
            or SubAgentProfile()
        )
        if max_steps:
            profile_obj = dataclasses.replace(profile_obj, max_steps=max_steps)

        runner = SubAgentRunner()
        return runner.run_sync(instruction, profile_obj, agent_cfg.llm_cfg_path, event_callback=step_callback)
