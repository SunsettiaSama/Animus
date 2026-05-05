from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from agent.base import AgentBase, AgentResult
from plan.document import PlanDocument, PlanTask, TaskExecutionContext, TaskStatus


class ExecutorAgent(AgentBase):
    role = "executor"

    def __init__(self, llm_cfg_path: str) -> None:
        self._llm_cfg_path = llm_cfg_path
        self._executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="executor")

    async def run(self, instruction: str, **ctx: Any) -> AgentResult:
        task: PlanTask = ctx["task"]
        doc: PlanDocument = ctx["doc"]

        agent_id = str(uuid.uuid4())
        await doc.update_task(task.task_id, status=TaskStatus.running)

        profile_name = task.params.get("profile", task.profile)
        max_steps = task.params.get("max_steps", task.max_steps)

        try:
            result = await asyncio.get_event_loop().run_in_executor(
                self._executor,
                self._run_sync,
                instruction,
                profile_name,
                max_steps,
            )
            step_count = result.get("step_count", 0)
            answer = result.get("answer", "")
            steps_log = result.get("steps_log", [])

            summary = answer[:300] if answer else ""
            exec_ctx = TaskExecutionContext(
                task_id=task.task_id,
                status="done",
                result_summary=summary,
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

        except Exception as exc:
            error_msg = str(exc)
            exec_ctx = TaskExecutionContext(
                task_id=task.task_id,
                status="failed",
                error=error_msg,
                retry_count=ctx.get("retry_count", 0),
            )
            await doc.update_task(
                task.task_id,
                status=TaskStatus.failed,
                error=error_msg,
                execution_ctx=exec_ctx,
            )
            return AgentResult(
                agent_id=agent_id,
                role=self.role,
                status="failed",
                output=error_msg,
                execution_ctx=exec_ctx,
            )

    def _run_sync(
        self,
        instruction: str,
        profile_name: str,
        max_steps: int | None,
    ) -> dict:
        from crew.config import CrewConfig, CrewProfile
        from crew.runner import CrewRunner
        from react.tao import FinishEvent, StepEvent

        profile = CrewProfile(
            max_steps=max_steps or 15,
            system_note="",
            tools=None,
            recursive=False,
            return_log=True,
        )

        # Build a minimal crew config with the requested profile
        crew_cfg = CrewConfig(
            llm_cfg_path=self._llm_cfg_path,
            profiles={profile_name: profile},
        )

        runner = CrewRunner()
        result = runner.run_sync(
            instruction=instruction,
            profile=profile,
            llm_cfg_path=self._llm_cfg_path,
            crew_cfg=crew_cfg,
        )
        return {
            "answer": result.answer,
            "step_count": len(result.log),
            "steps_log": result.log,
        }
