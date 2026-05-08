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
    cron_expr: str | None = None
    profile: str = "minimal"
    delivery: str = "push"
    max_retries: int = 0
    retry_delay_seconds: int = 60
    on_complete: str | None = None


class SchedulerTaskPatch(BaseModel):
    action: str  # "pause" | "resume" | "cancel"


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
    tasks = [t.to_dict() for t in eng.list_timeline()]
    for t in tasks:
        t["trigger_type"] = t.get("trigger", {}).get("type", "once")
    return {"tasks": tasks, "ready": True}


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

    kwargs = dict(
        profile=req.profile,
        delivery=req.delivery,
        max_retries=req.max_retries,
        retry_delay_seconds=req.retry_delay_seconds,
        on_complete=req.on_complete or None,
    )

    if req.trigger_type == "once":
        if not req.at:
            return JSONResponse(status_code=400, content={"error": "'at' is required for trigger_type='once'."})
        at_dt = datetime.fromisoformat(req.at.replace("Z", "+00:00"))
        if at_dt.tzinfo is None:
            at_dt = at_dt.replace(tzinfo=timezone.utc)
        task = eng.schedule_once(req.name, req.instruction, at_dt, **kwargs)

    elif req.trigger_type == "interval":
        if not req.interval_seconds or req.interval_seconds <= 0:
            return JSONResponse(status_code=400, content={"error": "'interval_seconds' must be > 0."})
        task = eng.schedule_interval(req.name, req.instruction, req.interval_seconds, **kwargs)

    elif req.trigger_type == "cron":
        if not req.cron_expr:
            return JSONResponse(status_code=400, content={"error": "'cron_expr' is required for trigger_type='cron'."})
        task = eng.schedule_cron(req.name, req.instruction, req.cron_expr, **kwargs)

    else:
        return JSONResponse(
            status_code=400,
            content={"error": f"Unknown trigger_type: {req.trigger_type!r}. Use 'once', 'interval', or 'cron'."},
        )

    return task.to_dict()


@router.patch("/api/scheduler/tasks/{task_id}")
def scheduler_patch(task_id: str, req: SchedulerTaskPatch):
    eng = _scheduler_engine()
    if eng is None:
        return JSONResponse(status_code=503, content={"error": "Scheduler not initialized."})

    if req.action == "pause":
        ok = eng.pause(task_id)
        if not ok:
            return JSONResponse(status_code=400, content={"error": "Task not found or not pausable."})
        return {"ok": True, "action": "pause", "task_id": task_id}

    if req.action == "resume":
        ok = eng.resume(task_id)
        if not ok:
            return JSONResponse(status_code=400, content={"error": "Task not found or not paused."})
        return {"ok": True, "action": "resume", "task_id": task_id}

    if req.action == "cancel":
        ok = eng.cancel(task_id)
        if not ok:
            return JSONResponse(status_code=404, content={"error": f"Task {task_id!r} not found."})
        return {"ok": True, "action": "cancel", "task_id": task_id}

    return JSONResponse(status_code=400, content={"error": f"Unknown action: {req.action!r}."})


@router.delete("/api/scheduler/tasks/{task_id}")
def scheduler_cancel(task_id: str):
    eng = _scheduler_engine()
    if eng is None:
        return JSONResponse(status_code=503, content={"error": "Scheduler not initialized."})
    ok = eng.cancel(task_id)
    if not ok:
        return JSONResponse(status_code=404, content={"error": f"Task {task_id!r} not found."})
    return {"cancelled": True, "task_id": task_id}


@router.get("/api/scheduler/proactive")
def scheduler_proactive_get():
    eng = _scheduler_engine()
    if eng is None:
        return {"proactive_enabled": True, "ready": False}
    return {"proactive_enabled": eng._cfg.proactive_enabled, "ready": True}


@router.patch("/api/scheduler/proactive")
def scheduler_proactive_set(body: dict):
    eng = _scheduler_engine()
    if eng is None:
        return JSONResponse(status_code=503, content={"error": "Scheduler not initialized."})
    enabled = bool(body.get("proactive_enabled", True))
    eng._cfg.proactive_enabled = enabled
    return {"proactive_enabled": enabled}


@router.get("/api/scheduler/axis")
def scheduler_axis():
    """Returns merged past timeline events + future scheduled tasks for the frontend axis."""
    from datetime import date
    state = get_state()
    eng = _scheduler_engine()

    # Past events from TimelineStore
    events: list[dict] = []
    if state.cache is not None:
        from agent.scheduler.timeline import TimelineStore
        tl = TimelineStore(state.cache.timeline_dir)
        events = tl.read(date.today().isoformat())

    # Future tasks (pending + paused) from TaskStore
    tasks: list[dict] = []
    if eng is not None:
        for t in eng.list_timeline():
            d = t.to_dict()
            d["trigger_type"] = t.trigger.type
            tasks.append(d)

    return {"events": events, "tasks": tasks}
