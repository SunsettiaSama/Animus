from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from state import get_state

router = APIRouter()


class SchedulerTaskCreate(BaseModel):
    name: str
    instruction: str
    trigger_type: str
    at: str | None = None
    interval_seconds: int | None = None
    profile: str = "minimal"


def _scheduler_engine():
    state = get_state()
    if state.active_tao is None or state.active_tao.scheduler_engine is None:
        return None
    return state.active_tao.scheduler_engine


@router.get("/api/scheduler/tasks")
def scheduler_list():
    eng = _scheduler_engine()
    if eng is None:
        return {"tasks": [], "ready": False}
    return {"tasks": [t.to_dict() for t in eng.list_timeline()], "ready": True}


@router.get("/api/scheduler/tasks/{task_id}")
def scheduler_get(task_id: str):
    eng = _scheduler_engine()
    if eng is None:
        return JSONResponse(status_code=503, content={"error": "Scheduler not initialized."})
    task = eng.get(task_id)
    if task is None:
        return JSONResponse(status_code=404, content={"error": f"Task {task_id!r} not found."})
    return task.to_dict()


@router.post("/api/scheduler/tasks")
def scheduler_create(req: SchedulerTaskCreate):
    from datetime import datetime, timezone
    eng = _scheduler_engine()
    if eng is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Scheduler not initialized. Initialize ReAct first."},
        )

    if req.trigger_type == "once":
        if not req.at:
            return JSONResponse(
                status_code=400,
                content={"error": "'at' is required for trigger_type='once'."},
            )
        at_dt = datetime.fromisoformat(req.at.replace("Z", "+00:00"))
        if at_dt.tzinfo is None:
            at_dt = at_dt.replace(tzinfo=timezone.utc)
        task = eng.schedule_once(req.name, req.instruction, at_dt, profile=req.profile)

    elif req.trigger_type == "interval":
        if not req.interval_seconds or req.interval_seconds <= 0:
            return JSONResponse(
                status_code=400,
                content={"error": "'interval_seconds' must be > 0 for trigger_type='interval'."},
            )
        task = eng.schedule_interval(
            req.name, req.instruction, req.interval_seconds, profile=req.profile
        )

    else:
        return JSONResponse(
            status_code=400,
            content={"error": f"Unknown trigger_type: {req.trigger_type!r}. Use 'once' or 'interval'."},
        )

    return task.to_dict()


@router.delete("/api/scheduler/tasks/{task_id}")
def scheduler_cancel(task_id: str):
    eng = _scheduler_engine()
    if eng is None:
        return JSONResponse(status_code=503, content={"error": "Scheduler not initialized."})
    ok = eng.cancel(task_id)
    if not ok:
        return JSONResponse(
            status_code=404,
            content={"error": f"Task {task_id!r} not found."},
        )
    return {"cancelled": True, "task_id": task_id}
