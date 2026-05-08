from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Callable

from agent.scheduler.config import SchedulerConfig
from agent.scheduler.store import TaskStore
from agent.scheduler.task import DeliveryMode, ScheduledTask, TaskStatus

if TYPE_CHECKING:
    from agent.scheduler.engine import SchedulerEngine

logger = logging.getLogger(__name__)


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
    def __init__(
        self,
        cfg: SchedulerConfig,
        long_term=None,
        timeline=None,
        notify_fn: Callable[[ScheduledTask, str], None] | None = None,
        engine: "SchedulerEngine | None" = None,
    ):
        self._cfg = cfg
        self._long_term = long_term
        self._timeline = timeline
        self._notify_fn = notify_fn
        self._engine = engine  # set post-init for task chain scheduling
        self._ltm_lock = threading.Lock()

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

        try:
            await asyncio.to_thread(_run_sync)
        except BaseException as exc:
            self._handle_failure(task, store, exc)
            raise

        # ── Finalize: file I/O + LTM + timeline — offloaded to thread pool ──────
        long_term   = self._long_term
        timeline    = self._timeline
        ltm_lock    = self._ltm_lock
        scheduler_dir = self._cfg.scheduler_dir

        def _finalize() -> str:
            path = _write_result(task, answer, scheduler_dir)
            if long_term is not None:
                summary = f"[调度任务] {task.name}\n指令: {task.instruction}\n结果: {answer}"
                with ltm_lock:
                    long_term.add(summary, source="scheduler", question=task.instruction)
                    long_term.save()
            if timeline is not None:
                timeline.append("scheduled_task", {
                    "task_id": task.id,
                    "task_name": task.name,
                    "instruction": task.instruction[:200],
                    "answer": answer[:500],
                })
            return path

        result_path = await asyncio.to_thread(_finalize)

        # ── Advance next_run_at ───────────────────────────────────────────────
        if task.trigger.type == "interval" and task.trigger.interval_seconds:
            next_run = datetime.now(timezone.utc) + timedelta(seconds=task.trigger.interval_seconds)
            store.update(
                task.id,
                status=TaskStatus.pending,
                next_run_at=next_run.isoformat(),
                last_result_path=result_path,
                retry_count=0,
            )
        elif task.trigger.type == "cron" and task.trigger.cron_expr:
            store.update(task.id, last_result_path=result_path, retry_count=0)
            store.advance_cron(task.id)
        else:
            store.update(task.id, status=TaskStatus.done, last_result_path=result_path, retry_count=0)

        # ── Task chain ────────────────────────────────────────────────────────
        if task.on_complete and self._engine is not None:
            ctx = task.context or {}
            next_instruction = task.on_complete.format(result=answer, **ctx)
            self._engine.schedule_once(
                name=f"{task.name}__chain",
                instruction=next_instruction,
                at=datetime.now(timezone.utc),
                profile=task.config_profile,
                reply_target=task.reply_target,
                delivery=task.delivery,
                on_complete=None,
            )

        # ── Delivery / Notification ───────────────────────────────────────────
        effective_delivery = task.delivery
        if not self._cfg.proactive_enabled and effective_delivery == DeliveryMode.push:
            effective_delivery = DeliveryMode.silent

        if effective_delivery == DeliveryMode.push and self._notify_fn is not None:
            notify_fn = self._notify_fn
            try:
                await asyncio.to_thread(notify_fn, task, answer)
            except Exception as exc:
                logger.error("[TaskRunner] notify_fn error for task %s: %s", task.id[:8], exc)
        elif effective_delivery == DeliveryMode.store_only and self._long_term is not None:
            _ltm     = self._long_term
            _lock    = self._ltm_lock
            _summary = f"[调度任务-归档] {task.name}\n{answer}"
            _instr   = task.instruction

            def _store_only() -> None:
                with _lock:
                    _ltm.add(_summary, source="scheduler_store_only", question=_instr)
                    _ltm.save()

            await asyncio.to_thread(_store_only)

    def _handle_failure(self, task: ScheduledTask, store: TaskStore, exc: BaseException) -> None:
        logger.error("[TaskRunner] task %s (%s) failed: %s", task.id[:8], task.name, exc)
        if task.retry_count < task.max_retries:
            next_run = datetime.now(timezone.utc) + timedelta(seconds=task.retry_delay_seconds)
            store.update(
                task.id,
                status=TaskStatus.pending,
                next_run_at=next_run.isoformat(),
                retry_count=task.retry_count + 1,
            )
            logger.info(
                "[TaskRunner] task %s rescheduled (attempt %d/%d) at %s",
                task.id[:8], task.retry_count + 1, task.max_retries, next_run.isoformat(),
            )
        else:
            store.update(task.id, status=TaskStatus.failed)
