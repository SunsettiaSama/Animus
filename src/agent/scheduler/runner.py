from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

from agent.scheduler.config import SchedulerConfig
from agent.scheduler.store import TaskStore
from agent.scheduler.task import ScheduledTask, TaskStatus


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_result(task: ScheduledTask, answer: str, scheduler_dir: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{task.id[:8]}_{ts}.json"
    path = os.path.join(scheduler_dir, "results", filename)
    payload = {
        "task_id": task.id,
        "task_name": task.name,
        "instruction": task.instruction,
        "executed_at": _utcnow_iso(),
        "answer": answer,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


class TaskRunner:
    def __init__(self, cfg: SchedulerConfig, long_term=None, timeline=None):
        self._cfg = cfg
        self._long_term = long_term
        self._timeline = timeline

    async def run(self, task: ScheduledTask, store: TaskStore) -> None:
        store.update(task.id, status=TaskStatus.running, last_run_at=_utcnow_iso())

        from agent.profile import SubAgentProfile
        profile: SubAgentProfile = (
            self._cfg.profiles.get(task.config_profile)
            or self._cfg.profiles.get("minimal")
            or SubAgentProfile()
        )

        answer = ""

        def _run_sync() -> None:
            nonlocal answer
            from agent.runner import SubAgentRunner
            runner = SubAgentRunner()
            result = runner.run_sync(task.instruction, profile, self._cfg.llm_cfg_path)
            answer = result["answer"]

        await asyncio.to_thread(_run_sync)

        result_path = _write_result(task, answer, self._cfg.scheduler_dir)

        if self._long_term is not None:
            summary = f"[调度任务] {task.name}\n指令: {task.instruction}\n结果: {answer}"
            self._long_term.add(summary, source="scheduler", question=task.instruction)
            self._long_term.save()

        if self._timeline is not None:
            self._timeline.append("scheduled_task", {
                "task_id": task.id,
                "task_name": task.name,
                "instruction": task.instruction[:200],
                "answer": answer[:500],
            })

        if task.trigger.type == "interval" and task.trigger.interval_seconds:
            next_run = datetime.now(timezone.utc) + timedelta(seconds=task.trigger.interval_seconds)
            store.update(
                task.id,
                status=TaskStatus.pending,
                next_run_at=next_run.isoformat(),
                last_result_path=result_path,
            )
        else:
            store.update(task.id, status=TaskStatus.done, last_result_path=result_path)
