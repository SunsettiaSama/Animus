from __future__ import annotations

import asyncio
import copy
import dataclasses
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
    from agent.scheduler.journal import WorkJournal
    from infra.channel_router import ChannelRouter, ReplyTarget

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
        journal: "WorkJournal | None" = None,
        channel_router: "ChannelRouter | None" = None,
    ):
        self._cfg = cfg
        self._long_term = long_term
        self._timeline = timeline
        self._notify_fn = notify_fn
        self._engine = engine
        self._journal = journal
        self._channel_router = channel_router
        self._ltm_lock = threading.Lock()

    async def run(self, task: ScheduledTask, store: TaskStore) -> None:
        store.update(task.id, status=TaskStatus.running, last_run_at=_utcnow_iso())

        from agent.profile import SubAgentProfile
        base_profile: SubAgentProfile = (
            self._cfg.profiles.get(task.config_profile)
            or self._cfg.profiles.get("minimal")
            or SubAgentProfile()
        )

        # Prepend scheduler_system_note to the profile's system_note
        combined_note = "\n\n".join(
            filter(None, [self._cfg.scheduler_system_note, base_profile.system_note])
        )
        profile = dataclasses.replace(base_profile, system_note=combined_note)

        answer = ""

        # Build mid-run notify function that writes to journal AND delivers via channel_router
        journal = self._journal
        channel_router = self._channel_router
        main_loop = None
        # Try to get the main event loop for thread-safe queue push
        try:
            import asyncio as _asyncio
            main_loop = _asyncio.get_event_loop()
        except RuntimeError:
            pass

        # We need notify_queue access for agent_message events
        # Resolved at runtime from the notify_fn closure context
        notify_fn_ref = self._notify_fn

        def _mid_run_notify(title: str, message: str) -> None:
            # 1. Write to WorkJournal (always)
            if journal is not None:
                journal.append_mid_run_message(task.id, task.name, title, message)
            # 2. Push agent_message to notify queue if available
            if notify_fn_ref is not None and main_loop is not None:
                item = {
                    "type": "agent_message",
                    "title": title,
                    "message": message,
                    "task_name": task.name,
                    "task_id": task.id,
                }
                # We push via a wrapper that knows the queue
                _push_agent_message(item)

        def _push_agent_message(item: dict) -> None:
            # Reach into the global AppState to get the notify queue
            # This avoids circular imports while allowing mid-run notifications
            from state import get_state
            st = get_state()
            if st.notify_queue is not None and st.main_event_loop is not None:
                st.main_event_loop.call_soon_threadsafe(st.notify_queue.put_nowait, item)
            # Also deliver via ChannelRouter if reply_target is set
            if channel_router is not None and task.reply_target is not None:
                from infra.channel_router import ReplyTarget as RT
                rt = RT.from_task_dict(task.reply_target)
                if rt is not None:
                    channel_router.deliver(rt, title, message)

        def _run_sync() -> None:
            nonlocal answer
            from agent.runner import SubAgentRunner
            runner = SubAgentRunner()
            result = runner.run_sync(
                task.instruction,
                profile,
                self._cfg.llm_cfg_path,
                notify_fn=_mid_run_notify,
                reply_target=task.reply_target,
            )
            answer = result["answer"]

        if journal is not None:
            journal.append_mid_run_message(task.id, task.name, "开始执行", task.instruction[:120])

        if main_loop is not None:
            _push_agent_message({
                "type": "agent_message",
                "title": f"[{task.name}] 开始执行",
                "message": task.instruction[:120],
                "task_name": task.name,
                "task_id": task.id,
            })

        try:
            await asyncio.to_thread(_run_sync)
        except BaseException as exc:
            self._handle_failure(task, store, exc)
            raise

        # ── Finalize: file I/O + LTM + timeline + journal ────────────────────
        long_term   = self._long_term
        timeline    = self._timeline
        ltm_lock    = self._ltm_lock
        scheduler_dir = self._cfg.scheduler_dir
        _journal    = self._journal

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
            if _journal is not None:
                _journal.append_task_result(task.id, task.name, task.instruction, answer)
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
            _nfn = self._notify_fn
            try:
                await asyncio.to_thread(_nfn, task, answer)
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
