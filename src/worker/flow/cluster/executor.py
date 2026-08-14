from __future__ import annotations

import asyncio
import dataclasses
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agent.base import AgentBase, AgentResult
from .document import PlanDocument, PlanTask, TaskExecutionContext, TaskStatus


def build_task_instruction(task: PlanTask, doc: PlanDocument) -> str:
    """Preserve graph dataflow by injecting objective and dependency outputs."""
    parts = [
        "=== Original Objective ===",
        doc.objective.strip(),
        "\n=== Current Task ===",
        task.description.strip(),
    ]
    dependencies: list[str] = []
    for dependency_id in task.depends_on:
        dependency = doc.get_task(dependency_id)
        result = str(dependency.result or "").strip()
        if result:
            dependencies.append(
                f"--- {dependency_id} ---\n{result}"
            )
    if dependencies:
        parts.extend(
            [
                "\n=== Dependency Results ===",
                "\n\n".join(dependencies),
            ]
        )
    parts.extend(
        [
            "\n=== Output Contract ===",
            (
                "Complete only the current task, using dependency results as "
                "authoritative inputs. Preserve every format, language, length, "
                "keyword, and content constraint from the original objective. "
                "Return only the current task result."
            ),
        ]
    )
    return "\n".join(parts)


class ExecutorAgent(AgentBase):
    role = "executor"

    def __init__(
        self,
        llm_cfg_path: str,
        agent_cfg: Any = None,
        executor_pool: ThreadPoolExecutor | None = None,
        agent_state_service: Any = None,
    ) -> None:
        self._llm_cfg_path = llm_cfg_path
        self._agent_cfg = agent_cfg
        self._agent_state_service = agent_state_service
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

        capability_card_id = task.params.get(
            "capability_card_id", task.capability_card_id
        )
        max_steps = task.params.get("max_steps", task.max_steps)

        result = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            self._run_sync,
            build_task_instruction(task, doc),
            capability_card_id,
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
        capability_card_id: str,
        max_steps: int | None,
        step_callback=None,
    ) -> dict:
        from worker.profile import SubAgentConfig
        from worker.runner import SubAgentRunner

        agent_cfg: SubAgentConfig = self._agent_cfg or SubAgentConfig()

        profile_obj = agent_cfg.resolve_profile(capability_card_id)
        if max_steps:
            profile_obj = dataclasses.replace(profile_obj, max_steps=max_steps)

        runner = SubAgentRunner()
        return runner.run_sync(
            instruction,
            profile_obj,
            agent_cfg.llm_cfg_path,
            event_callback=step_callback,
            agent_state_service=self._agent_state_service,
        )
