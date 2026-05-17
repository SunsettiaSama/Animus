from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from state import get_state

router = APIRouter()


# ── Request models ─────────────────────────────────────────────────────────────

class RunPlanRequest(BaseModel):
    question: str
    plan_dir: str = ".cache/plans"
    llm_cfg_path: str = ""


class RollbackRequest(BaseModel):
    snapshot_id: str


class SkipRequest(BaseModel):
    cascade: bool = False


class TaskPatchRequest(BaseModel):
    description: str | None = None
    profile: str | None = None
    max_steps: int | None = None


class HumanMessageRequest(BaseModel):
    message: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _plan_event_to_dict(event) -> dict:
    # Raw dicts (log_line, replanner_thinking) pass through unchanged
    if isinstance(event, dict):
        return event
    from plan.event import (
        HumanPatchEvent, LifecycleStateEvent,
        LogLineEvent, NodeExpansionRequestEvent,
        PlanAbortEvent, PlanCompleteEvent, PlanStartEvent,
        PlannerStepEvent, ReplanEvent,
        ReplannerCompleteEvent, ReplannerStartEvent, ReplannerThinkingEvent,
        SnapshotEvent, TaskCompleteEvent, TaskFailedEvent,
        TaskRunningEvent, TaskSkippedEvent, TaskStartEvent, TaskStepEvent,
    )
    if isinstance(event, PlanStartEvent):
        return {"type": "plan_start", "plan_id": event.plan_id, "title": event.title, "task_count": event.task_count}
    if isinstance(event, TaskStartEvent):
        return {"type": "task_start", "plan_id": event.plan_id, "task_id": event.task_id, "module": event.module, "profile": event.profile}
    if isinstance(event, TaskRunningEvent):
        return {"type": "task_running", "plan_id": event.plan_id, "task_id": event.task_id}
    if isinstance(event, TaskCompleteEvent):
        return {"type": "task_complete", "plan_id": event.plan_id, "task_id": event.task_id, "result_preview": event.result_preview}
    if isinstance(event, TaskFailedEvent):
        return {"type": "task_failed", "plan_id": event.plan_id, "task_id": event.task_id, "error": event.error}
    if isinstance(event, TaskSkippedEvent):
        return {"type": "task_skipped", "plan_id": event.plan_id, "task_id": event.task_id, "reason": event.reason}
    if isinstance(event, ReplanEvent):
        return {"type": "replan", "plan_id": event.plan_id, "trigger": event.trigger, "decision": event.decision, "patches_count": event.patches_count, "cycle": event.cycle}
    if isinstance(event, HumanPatchEvent):
        return {"type": "human_patch", "plan_id": event.plan_id, "patches_count": event.patches_count, "patch_ops": event.patch_ops}
    if isinstance(event, SnapshotEvent):
        return {"type": "snapshot", "plan_id": event.plan_id, "snapshot_id": event.snapshot_id, "trigger": event.trigger}
    if isinstance(event, PlanCompleteEvent):
        return {"type": "plan_complete", "plan_id": event.plan_id, "conclusion": event.conclusion}
    if isinstance(event, PlanAbortEvent):
        return {"type": "plan_abort", "plan_id": event.plan_id, "reason": event.reason}
    if isinstance(event, LifecycleStateEvent):
        return {"type": "lifecycle_state", "plan_id": event.plan_id, "state": event.state}
    if isinstance(event, TaskStepEvent):
        return {"type": "task_step", "plan_id": event.plan_id, "task_id": event.task_id, "step": event.step}
    if isinstance(event, PlannerStepEvent):
        return {
            "type": "planner_step",
            "plan_id": event.plan_id,
            "phase": event.phase,
            "step_index": event.step_index,
            "thought": event.thought,
            "action": event.action,
            "observation": event.observation,
        }
    if isinstance(event, ReplannerStartEvent):
        return {"type": "replanner_start", "plan_id": event.plan_id, "trigger": event.trigger, "cycle": event.cycle}
    if isinstance(event, ReplannerCompleteEvent):
        return {
            "type": "replanner_complete",
            "plan_id": event.plan_id,
            "decision": event.decision,
            "reason": event.reason,
            "patches_count": event.patches_count,
        }
    if isinstance(event, ReplannerThinkingEvent):
        return {"type": "replanner_thinking", "plan_id": event.plan_id, "stage": event.stage, "cycle": event.cycle}
    if isinstance(event, NodeExpansionRequestEvent):
        return {
            "type": "node_expansion_request",
            "plan_id": event.plan_id,
            "task_id": event.task_id,
            "reason": event.reason,
            "suggested_subtasks": event.suggested_subtasks,
        }
    if isinstance(event, LogLineEvent):
        return {"type": "log_line", "plan_id": event.plan_id, "level": event.level, "event": event.event, **event.payload}
    return {"type": "unknown"}


# ── POST /api/plan/run ─────────────────────────────────────────────────────────

@router.post("/api/plan/run")
async def run_plan(req: RunPlanRequest) -> JSONResponse:
    state = get_state()

    from plan.config import OrchestratorConfig, PlannerConfig, ReplannerConfig, LogConfig
    from plan.orchestrator import PlanOrchestrator

    llm_cfg_path = req.llm_cfg_path or state.llm_config_yaml

    cfg = OrchestratorConfig(
        plan_dir=req.plan_dir,
        planner=PlannerConfig(),
        replanner=ReplannerConfig(),
        log=LogConfig(),
    )

    orchestrator = PlanOrchestrator(cfg=cfg, llm_cfg_path=llm_cfg_path)

    def _on_event(event) -> None:
        state.plan_broadcast(_plan_event_to_dict(event))

    orchestrator.subscribe(_on_event)
    state.active_orchestrator = orchestrator

    async def _run() -> None:
        t_start = time.time()
        result = await orchestrator.run(req.question)
        state.plan_broadcast({"type": "done", "status": result.status, "answer": result.answer or ""})
        # Persist history record
        from plan.history import PlanHistoryStore
        from config import paths
        history_dir = Path(paths.cache_root) / "plans" / "history"
        store = PlanHistoryStore(str(history_dir))
        doc = result.doc
        store.save({
            "plan_id": result.plan_id,
            "question": req.question,
            "title": doc.title if doc else "",
            "status": result.status,
            "answer": result.answer or "",
            "task_count": len(doc.all_tasks()) if doc else 0,
            "plan_dir": req.plan_dir,
            "completed_at": time.time(),
            "elapsed_sec": round(time.time() - t_start, 1),
        })

    asyncio.create_task(_run())
    return JSONResponse({"status": "started", "message": "Plan execution started."})


# ── GET /api/plan/status ───────────────────────────────────────────────────────

@router.get("/api/plan/status")
def plan_status() -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_doc is None:
        return JSONResponse({"status": "idle", "doc": None})

    doc = orch._current_doc
    return JSONResponse({
        "status": "running",
        "doc": doc.to_dict(),
    })


# ── GET /api/plan/stream  (SSE) ────────────────────────────────────────────────

@router.get("/api/plan/stream")
async def plan_stream() -> StreamingResponse:
    state = get_state()
    q = state.plan_subscribe()

    async def _generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                event_dict = await q.get()
                yield f"data: {json.dumps(event_dict, ensure_ascii=False)}\n\n"
                if event_dict.get("type") in ("done", "plan_complete", "plan_abort"):
                    break
        finally:
            state.plan_unsubscribe(q)

    return StreamingResponse(_generator(), media_type="text/event-stream")


# ── GET /api/plan/snapshots ────────────────────────────────────────────────────

@router.get("/api/plan/snapshots")
def plan_snapshots() -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_snapshots is None:
        return JSONResponse([])

    snaps = orch._current_snapshots.list()
    return JSONResponse([
        {
            "snapshot_id": s.snapshot_id,
            "plan_id": s.plan_id,
            "timestamp": s.timestamp,
            "trigger": s.trigger,
            "cycle": s.cycle,
        }
        for s in snaps
    ])


# ── POST /api/plan/rollback ────────────────────────────────────────────────────

@router.post("/api/plan/rollback")
def plan_rollback(req: RollbackRequest) -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_snapshots is None:
        return JSONResponse({"error": "No active plan"}, status_code=400)

    new_doc = orch._current_snapshots.rollback(req.snapshot_id)
    orch._current_doc = new_doc
    return JSONResponse({"status": "ok", "snapshot_id": req.snapshot_id})


# ── GET /api/plan/logs ─────────────────────────────────────────────────────────

@router.get("/api/plan/logs")
async def plan_logs(n: int = 100, task_id: str | None = None) -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_logger is None:
        return JSONResponse([])

    from plan.log import LogLevel
    records = await orch._current_logger.read_async(
        level_min=LogLevel.DEBUG,
        task_id=task_id or None,
        n=n,
    )
    return JSONResponse(records)


# ── POST /api/plan/pause ───────────────────────────────────────────────────────

@router.post("/api/plan/pause")
def plan_pause() -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_doc is None:
        return JSONResponse({"error": "No active plan"}, status_code=400)
    orch._current_doc.pause()
    return JSONResponse({"status": "paused"})


@router.post("/api/plan/resume")
def plan_resume() -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_doc is None:
        return JSONResponse({"error": "No active plan"}, status_code=400)
    orch._current_doc.resume()
    return JSONResponse({"status": "resumed"})


# ── POST /api/plan/skip/{task_id} ──────────────────────────────────────────────

@router.get("/api/plan/task/{task_id}/steps")
def plan_task_steps(task_id: str) -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    steps = (orch._task_steps.get(task_id, []) if orch is not None else [])
    return JSONResponse({"task_id": task_id, "steps": steps})


@router.post("/api/plan/skip/{task_id}")
def plan_skip(task_id: str, req: SkipRequest = SkipRequest()) -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_doc is None:
        return JSONResponse({"error": "No active plan"}, status_code=400)
    orch._current_doc.skip(task_id, cascade=req.cascade)
    return JSONResponse({"status": "skipped", "task_id": task_id})


# ── PATCH /api/plan/tasks/{task_id} ───────────────────────────────────────────

@router.patch("/api/plan/tasks/{task_id}")
async def plan_task_patch(task_id: str, req: TaskPatchRequest) -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_doc is None:
        return JSONResponse({"error": "No active plan"}, status_code=400)
    from plan.document import TaskStatus
    task = orch._current_doc.get_task(task_id)
    if task.status != TaskStatus.pending:
        return JSONResponse(
            {"error": f"Task '{task_id}' is not in pending state (current: {task.status.value})"},
            status_code=409,
        )
    updates: dict = {}
    if req.description is not None:
        updates["description"] = req.description
    if req.profile is not None:
        updates["profile"] = req.profile
    if req.max_steps is not None:
        updates["max_steps"] = req.max_steps
    if updates:
        await orch._current_doc.update_task(task_id, **updates)
        state.plan_broadcast({"type": "task_updated", "task_id": task_id, "updates": updates})
    return JSONResponse({"status": "ok", "task_id": task_id, "updates": updates})


# ── POST /api/plan/human-request ───────────────────────────────────────────────

@router.post("/api/plan/human-request")
async def plan_human_request(req: HumanMessageRequest) -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_doc is None:
        return JSONResponse({"error": "No active plan"}, status_code=400)
    from plan.patch import HumanPatch, PatchOp
    replan_patch = HumanPatch(op=PatchOp.replan, task_id=None, payload={"human_message": req.message})
    logger = orch._current_logger
    snapshots = orch._current_snapshots
    plan_id = orch.current_plan_id or ""
    if logger and snapshots:
        await orch._call_replanner(
            orch._current_doc, snapshots, logger, plan_id, trigger="on_human_request"
        )
    state.plan_broadcast({"type": "human_request_received", "message": req.message})
    return JSONResponse({"status": "ok", "message": "Human request forwarded to replanner."})


# ── GET /api/plan/history ──────────────────────────────────────────────────────

def _get_history_store():
    from plan.history import PlanHistoryStore
    from config import paths
    history_dir = Path(paths.cache_root) / "plans" / "history"
    return PlanHistoryStore(str(history_dir))


@router.get("/api/plan/history")
def plan_history_list() -> JSONResponse:
    store = _get_history_store()
    return JSONResponse(store.list_all())


@router.delete("/api/plan/history/{plan_id}")
def plan_history_delete(plan_id: str) -> JSONResponse:
    store = _get_history_store()
    store.delete(plan_id)
    return JSONResponse({"status": "deleted", "plan_id": plan_id})
