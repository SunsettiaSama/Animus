from __future__ import annotations

import asyncio
import json
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _plan_event_to_dict(event) -> dict:
    from plan.event import (
        HumanPatchEvent,
        PlanAbortEvent,
        PlanCompleteEvent,
        PlanStartEvent,
        ReplanEvent,
        SnapshotEvent,
        TaskCompleteEvent,
        TaskFailedEvent,
        TaskRunningEvent,
        TaskSkippedEvent,
        TaskStartEvent,
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

    event_queue: asyncio.Queue = asyncio.Queue()

    def _on_event(event) -> None:
        event_queue.put_nowait(_plan_event_to_dict(event))

    orchestrator.subscribe(_on_event)
    state.active_orchestrator = orchestrator
    state.plan_event_queue = event_queue

    async def _run() -> None:
        result = await orchestrator.run(req.question)
        await event_queue.put({"type": "done", "status": result.status, "answer": result.answer})

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

    async def _generator() -> AsyncGenerator[str, None]:
        queue = state.plan_event_queue
        if queue is None:
            yield "data: {}\n\n"
            return
        while True:
            event_dict = await queue.get()
            yield f"data: {json.dumps(event_dict, ensure_ascii=False)}\n\n"
            if event_dict.get("type") in ("done", "plan_complete", "plan_abort"):
                break

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

@router.post("/api/plan/skip/{task_id}")
def plan_skip(task_id: str, req: SkipRequest = SkipRequest()) -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_doc is None:
        return JSONResponse({"error": "No active plan"}, status_code=400)
    orch._current_doc.skip(task_id, cascade=req.cascade)
    return JSONResponse({"status": "skipped", "task_id": task_id})
