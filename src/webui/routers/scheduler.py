from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import APIRouter, Request
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
    command: dict | None = None


class SchedulerTaskPatch(BaseModel):
    action: str           # "pause" | "resume" | "cancel" | "edit"
    at: str | None = None
    name: str | None = None
    instruction: str | None = None
    command: dict | None = None


class SchedulerConfigPatch(BaseModel):
    poll_interval: float | None = None
    proactive_enabled: bool | None = None
    scheduler_system_note: str | None = None
    default_profile: str | None = None
    max_concurrent: int | None = None
    task_retention_days: int | None = None
    profile_max_steps: dict | None = None   # {"minimal": 10, "with_memory": 15, ...}
    heartbeat: dict | None = None           # nested HeartbeatConfig fields
    comm_notify_rpm: int | None = None
    comm_notify_rph: int | None = None
    comm_bot_rpm: int | None = None
    comm_bot_rph: int | None = None


class SchedulerControlRequest(BaseModel):
    action: str   # "pause" | "resume" | "stop"


def _scheduler_engine():
    state = get_state()
    # Prefer the global scheduler engine; fall back to active_tao's engine
    if state.scheduler_engine is not None:
        return state.scheduler_engine
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

    # If a command dict is provided, render instruction from it
    instruction = req.instruction
    if req.command:
        from agent.scheduler.command import EventCommand
        instruction = EventCommand.from_dict(req.command).render() or instruction

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
        task = eng.schedule_once(req.name, instruction, at_dt, **kwargs)

    elif req.trigger_type == "interval":
        if not req.interval_seconds or req.interval_seconds <= 0:
            return JSONResponse(status_code=400, content={"error": "'interval_seconds' must be > 0."})
        task = eng.schedule_interval(req.name, instruction, req.interval_seconds, **kwargs)

    elif req.trigger_type == "cron":
        if not req.cron_expr:
            return JSONResponse(status_code=400, content={"error": "'cron_expr' is required for trigger_type='cron'."})
        task = eng.schedule_cron(req.name, instruction, req.cron_expr, **kwargs)

    else:
        return JSONResponse(
            status_code=400,
            content={"error": f"Unknown trigger_type: {req.trigger_type!r}. Use 'once', 'interval', or 'cron'."},
        )

    # Store command metadata if provided
    if req.command:
        eng._store.update(task.id, command=req.command)

    return task.to_dict()


@router.patch("/api/scheduler/tasks/{task_id}")
def scheduler_patch(task_id: str, req: SchedulerTaskPatch):
    from datetime import datetime, timezone
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

    if req.action == "edit":
        task = eng.get(task_id)
        if task is None:
            return JSONResponse(status_code=404, content={"error": f"Task {task_id!r} not found."})

        fields: dict = {}
        if req.name is not None:
            fields["name"] = req.name
        if req.at is not None:
            if task.trigger.type != "once":
                return JSONResponse(status_code=400, content={"error": "Can only reschedule 'once' trigger tasks."})
            at_dt = datetime.fromisoformat(req.at.replace("Z", "+00:00"))
            if at_dt.tzinfo is None:
                at_dt = at_dt.replace(tzinfo=timezone.utc)
            fields["next_run_at"] = at_dt.isoformat()
        if req.command is not None:
            from agent.scheduler.command import EventCommand
            fields["command"] = req.command
            fields["instruction"] = EventCommand.from_dict(req.command).render()
        elif req.instruction is not None:
            fields["instruction"] = req.instruction

        if fields:
            eng._store.update(task_id, **fields)
        updated = eng.get(task_id)
        return updated.to_dict() if updated else {"ok": True}

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


@router.get("/api/scheduler/status")
def scheduler_status():
    eng = _scheduler_engine()
    if eng is None:
        return {
            "engine_ready": False,
            "is_running": False,
            "is_paused": False,
            "poll_interval": 1.0,
            "task_counts": {"total": 0, "pending": 0, "running": 0, "done": 0, "cancelled": 0, "failed": 0},
            "server_timezone": _server_tz(),
        }
    tasks = eng.list_timeline()
    counts: dict[str, int] = {"total": len(tasks), "pending": 0, "running": 0, "done": 0, "cancelled": 0, "failed": 0}
    for t in tasks:
        key = str(t.status.value) if hasattr(t.status, "value") else str(t.status)
        if key in counts:
            counts[key] += 1
    return {
        "engine_ready": True,
        "is_running": eng.is_clock_running,
        "is_paused": eng.is_clock_paused,
        "poll_interval": eng._cfg.poll_interval,
        "task_counts": counts,
        "server_timezone": _server_tz(),
    }


@router.post("/api/scheduler/control")
def scheduler_control(req: SchedulerControlRequest):
    eng = _scheduler_engine()
    if eng is None:
        return JSONResponse(status_code=503, content={"error": "Scheduler not initialized."})

    if req.action == "pause":
        eng.pause_clock()
        return {"ok": True, "action": "pause", "is_paused": eng.is_clock_paused}

    if req.action == "resume":
        eng.resume_clock()
        return {"ok": True, "action": "resume", "is_paused": eng.is_clock_paused}

    if req.action == "stop":
        return JSONResponse(
            status_code=403,
            content={"error": "Stopping the engine is not supported from the UI to avoid breaking agent state. Use pause instead."},
        )

    return JSONResponse(status_code=400, content={"error": f"Unknown action: {req.action!r}. Use 'pause' or 'resume'."})


def _server_tz() -> str:
    import time as _time
    return _time.tzname[0] if _time.daylight == 0 else _time.tzname[1]


@router.get("/api/scheduler/config")
def scheduler_config_get():
    eng = _scheduler_engine()
    if eng is None:
        return JSONResponse(status_code=503, content={"error": "Scheduler not initialized."})
    cfg = eng._cfg
    profiles_info = {}
    for k, p in cfg.profiles.items():
        profiles_info[k] = {"max_steps": getattr(p, "max_steps", 10)}
    return {
        "poll_interval": cfg.poll_interval,
        "proactive_enabled": cfg.proactive_enabled,
        "scheduler_system_note": cfg.scheduler_system_note,
        "default_profile": cfg.default_profile,
        "max_concurrent": cfg.max_concurrent,
        "task_retention_days": cfg.task_retention_days,
        "profiles": profiles_info,
        "heartbeat": cfg.heartbeat.to_dict(),
        "comm_notify_rpm": getattr(cfg, "comm_notify_rpm", 5),
        "comm_notify_rph": getattr(cfg, "comm_notify_rph", 20),
        "comm_bot_rpm":    getattr(cfg, "comm_bot_rpm", 3),
        "comm_bot_rph":    getattr(cfg, "comm_bot_rph", 15),
    }


@router.patch("/api/scheduler/config")
def scheduler_config_set(req: SchedulerConfigPatch):
    import yaml
    state = get_state()
    eng = _scheduler_engine()
    if eng is None:
        return JSONResponse(status_code=503, content={"error": "Scheduler not initialized."})
    cfg = eng._cfg

    if req.poll_interval is not None:
        if req.poll_interval < 1.0:
            return JSONResponse(status_code=400, content={"error": "poll_interval must be >= 1.0"})
        cfg.poll_interval = req.poll_interval
    if req.proactive_enabled is not None:
        cfg.proactive_enabled = req.proactive_enabled
    if req.scheduler_system_note is not None:
        cfg.scheduler_system_note = req.scheduler_system_note
    if req.default_profile is not None:
        cfg.default_profile = req.default_profile
    if req.max_concurrent is not None:
        if req.max_concurrent < 1:
            return JSONResponse(status_code=400, content={"error": "max_concurrent must be >= 1"})
        cfg.max_concurrent = req.max_concurrent
    if req.task_retention_days is not None:
        if req.task_retention_days < 0:
            return JSONResponse(status_code=400, content={"error": "task_retention_days must be >= 0"})
        cfg.task_retention_days = req.task_retention_days
    if req.profile_max_steps is not None:
        for profile_name, max_steps in req.profile_max_steps.items():
            if profile_name in cfg.profiles:
                cfg.profiles[profile_name].max_steps = int(max_steps)

    # Patch nested heartbeat config
    if req.heartbeat is not None:
        hb = cfg.heartbeat
        for k, v in req.heartbeat.items():
            if hasattr(hb, k):
                setattr(hb, k, type(getattr(hb, k))(v))

    # Comm rate limits
    if req.comm_notify_rpm is not None:
        cfg.comm_notify_rpm = req.comm_notify_rpm
    if req.comm_notify_rph is not None:
        cfg.comm_notify_rph = req.comm_notify_rph
    if req.comm_bot_rpm is not None:
        cfg.comm_bot_rpm = req.comm_bot_rpm
    if req.comm_bot_rph is not None:
        cfg.comm_bot_rph = req.comm_bot_rph

    # Persist to YAML
    if state.scheduler_config_yaml:
        save_dict = cfg.to_dict()
        with open(state.scheduler_config_yaml, "w", encoding="utf-8") as f:
            yaml.dump(save_dict, f, allow_unicode=True, default_flow_style=False)

    profiles_info = {k: {"max_steps": getattr(p, "max_steps", 10)} for k, p in cfg.profiles.items()}
    return {
        "poll_interval": cfg.poll_interval,
        "proactive_enabled": cfg.proactive_enabled,
        "scheduler_system_note": cfg.scheduler_system_note,
        "default_profile": cfg.default_profile,
        "max_concurrent": cfg.max_concurrent,
        "task_retention_days": cfg.task_retention_days,
        "profiles": profiles_info,
        "heartbeat": cfg.heartbeat.to_dict(),
        "comm_notify_rpm": getattr(cfg, "comm_notify_rpm", 5),
        "comm_notify_rph": getattr(cfg, "comm_notify_rph", 20),
        "comm_bot_rpm":    getattr(cfg, "comm_bot_rpm", 3),
        "comm_bot_rph":    getattr(cfg, "comm_bot_rph", 15),
    }


@router.get("/api/scheduler/journal")
def scheduler_journal_get(date: str | None = None):
    state = get_state()
    journal = getattr(state, "scheduler_journal", None)
    if journal is None:
        return {"conv_id": "", "messages": [], "ready": False}
    data = journal.read(date)
    return {
        "conv_id": data.get("id", ""),
        "title": data.get("title", ""),
        "messages": data.get("messages", []),
        "ready": True,
    }


@router.get("/api/scheduler/heartbeat-file")
def heartbeat_file_get():
    eng = _scheduler_engine()
    if eng is None:
        return JSONResponse(status_code=503, content={"error": "Scheduler not initialized."})
    content = eng.heartbeat.read_file()
    return {"content": content}


class HeartbeatFileBody(BaseModel):
    content: str


@router.put("/api/scheduler/heartbeat-file")
def heartbeat_file_put(body: HeartbeatFileBody):
    eng = _scheduler_engine()
    if eng is None:
        return JSONResponse(status_code=503, content={"error": "Scheduler not initialized."})
    eng.heartbeat.write_file(body.content)
    return {"ok": True}


@router.get("/api/scheduler/heartbeat-log")
def heartbeat_log_get(n: int = 50):
    eng = _scheduler_engine()
    if eng is None:
        return {"entries": [], "ready": False}
    entries = eng.heartbeat.recent_log(n=n)
    return {"entries": entries, "ready": True}


@router.post("/api/scheduler/webhook/heartbeat")
async def webhook_heartbeat(request: Request):
    eng = _scheduler_engine()
    if eng is None:
        return JSONResponse(status_code=503, content={"error": "Scheduler not initialized."})

    secret = eng._cfg.heartbeat.webhook_secret
    if secret:
        sig_header = request.headers.get("X-Signature-SHA256", "")
        body = await request.body()
        expected = "sha256=" + hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, sig_header):
            return JSONResponse(status_code=401, content={"error": "Invalid signature."})

    eng.trigger_proactive_now()
    return {"ok": True, "triggered_at": time.time()}


@router.get("/api/scheduler/axis")
def scheduler_axis():
    """Returns merged past timeline events + future scheduled tasks for the frontend axis."""
    from datetime import date
    state = get_state()
    eng = _scheduler_engine()

    events: list[dict] = []
    if state.cache is not None:
        from agent.scheduler.timeline import TimelineStore
        tl = TimelineStore(state.cache.timeline_dir)
        events = tl.read(date.today().isoformat())

    tasks: list[dict] = []
    if eng is not None:
        for t in eng.list_timeline():
            d = t.to_dict()
            d["trigger_type"] = t.trigger.type
            tasks.append(d)

    return {"events": events, "tasks": tasks}
