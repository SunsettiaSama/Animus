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


def _with_flow_id(d: dict) -> dict:
    if "plan_id" in d and "flow_id" not in d:
        d = dict(d)
        d["flow_id"] = d["plan_id"]
    return d


class RunFlowRequest(BaseModel):
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


def _flow_event_to_dict(event) -> dict:
    if isinstance(event, dict):
        return _with_flow_id(event)
    from agent.flow.event import (
        HumanPatchEvent,
        LifecycleStateEvent,
        LogLineEvent,
        NodeExpansionRequestEvent,
        PlanAbortEvent,
        PlanCompleteEvent,
        PlanStartEvent,
        PlannerStepEvent,
        ReplanEvent,
        ReplannerCompleteEvent,
        ReplannerStartEvent,
        ReplannerThinkingEvent,
        SnapshotEvent,
        TaskCompleteEvent,
        TaskFailedEvent,
        TaskRunningEvent,
        TaskSkippedEvent,
        TaskStartEvent,
        TaskStepEvent,
    )
    if isinstance(event, PlanStartEvent):
        return _with_flow_id({"type": "plan_start", "plan_id": event.plan_id, "title": event.title, "task_count": event.task_count})
    if isinstance(event, TaskStartEvent):
        return _with_flow_id({"type": "task_start", "plan_id": event.plan_id, "task_id": event.task_id, "module": event.module, "profile": event.profile})
    if isinstance(event, TaskRunningEvent):
        return _with_flow_id({"type": "task_running", "plan_id": event.plan_id, "task_id": event.task_id})
    if isinstance(event, TaskCompleteEvent):
        return _with_flow_id({"type": "task_complete", "plan_id": event.plan_id, "task_id": event.task_id, "result_preview": event.result_preview})
    if isinstance(event, TaskFailedEvent):
        return _with_flow_id({"type": "task_failed", "plan_id": event.plan_id, "task_id": event.task_id, "error": event.error})
    if isinstance(event, TaskSkippedEvent):
        return _with_flow_id({"type": "task_skipped", "plan_id": event.plan_id, "task_id": event.task_id, "reason": event.reason})
    if isinstance(event, ReplanEvent):
        return _with_flow_id({"type": "replan", "plan_id": event.plan_id, "trigger": event.trigger, "decision": event.decision, "patches_count": event.patches_count, "cycle": event.cycle})
    if isinstance(event, HumanPatchEvent):
        return _with_flow_id({"type": "human_patch", "plan_id": event.plan_id, "patches_count": event.patches_count, "patch_ops": event.patch_ops})
    if isinstance(event, SnapshotEvent):
        return _with_flow_id({"type": "snapshot", "plan_id": event.plan_id, "snapshot_id": event.snapshot_id, "trigger": event.trigger})
    if isinstance(event, PlanCompleteEvent):
        return _with_flow_id({"type": "plan_complete", "plan_id": event.plan_id, "conclusion": event.conclusion})
    if isinstance(event, PlanAbortEvent):
        return _with_flow_id({"type": "plan_abort", "plan_id": event.plan_id, "reason": event.reason})
    if isinstance(event, LifecycleStateEvent):
        return _with_flow_id({"type": "lifecycle_state", "plan_id": event.plan_id, "state": event.state})
    if isinstance(event, TaskStepEvent):
        return _with_flow_id({"type": "task_step", "plan_id": event.plan_id, "task_id": event.task_id, "step": event.step})
    if isinstance(event, PlannerStepEvent):
        return _with_flow_id({
            "type": "planner_step",
            "plan_id": event.plan_id,
            "phase": event.phase,
            "step_index": event.step_index,
            "thought": event.thought,
            "action": event.action,
            "observation": event.observation,
        })
    if isinstance(event, ReplannerStartEvent):
        return _with_flow_id({"type": "replanner_start", "plan_id": event.plan_id, "trigger": event.trigger, "cycle": event.cycle})
    if isinstance(event, ReplannerCompleteEvent):
        return _with_flow_id({
            "type": "replanner_complete",
            "plan_id": event.plan_id,
            "decision": event.decision,
            "reason": event.reason,
            "patches_count": event.patches_count,
        })
    if isinstance(event, ReplannerThinkingEvent):
        return _with_flow_id({"type": "replanner_thinking", "plan_id": event.plan_id, "stage": event.stage, "cycle": event.cycle})
    if isinstance(event, NodeExpansionRequestEvent):
        return _with_flow_id({
            "type": "node_expansion_request",
            "plan_id": event.plan_id,
            "task_id": event.task_id,
            "reason": event.reason,
            "suggested_subtasks": event.suggested_subtasks,
        })
    if isinstance(event, LogLineEvent):
        return _with_flow_id({"type": "log_line", "plan_id": event.plan_id, "level": event.level, "event": event.event, **event.payload})
    return {"type": "unknown"}


@router.post("/api/flow/run")
async def run_flow(req: RunFlowRequest) -> JSONResponse:
    state = get_state()

    from agent.flow.config import LogConfig, OrchestratorConfig, PlannerConfig, ReplannerConfig
    from agent.flow.orchestrator import FlowOrchestrator

    llm_cfg_path = req.llm_cfg_path or state.llm_config_yaml

    cfg = OrchestratorConfig(
        plan_dir=req.plan_dir,
        planner=PlannerConfig(),
        replanner=ReplannerConfig(),
        log=LogConfig(),
    )

    orchestrator = FlowOrchestrator(cfg=cfg, llm_cfg_path=llm_cfg_path)

    def _on_event(event) -> None:
        state.flow_broadcast(_flow_event_to_dict(event))

    orchestrator.subscribe(_on_event)
    state.active_orchestrator = orchestrator

    async def _run() -> None:
        t_start = time.time()
        result = await orchestrator.run(req.question)
        state.flow_broadcast(_with_flow_id({"type": "done", "status": result.status, "answer": result.answer or ""}))
        from agent.flow.history import PlanHistoryStore
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
    return JSONResponse({"status": "started", "message": "Flow execution started."})


@router.get("/api/flow/status")
def flow_status() -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_doc is None:
        return JSONResponse({"status": "idle", "doc": None})

    doc = orch._current_doc
    return JSONResponse({
        "status": "running",
        "doc": doc.to_dict(),
    })


@router.get("/api/flow/stream")
async def flow_stream() -> StreamingResponse:
    state = get_state()
    q = state.flow_subscribe()

    async def _generator() -> AsyncGenerator[str, None]:
        try:
            while True:
                event_dict = await q.get()
                yield f"data: {json.dumps(event_dict, ensure_ascii=False)}\n\n"
                if event_dict.get("type") in ("done", "plan_complete", "plan_abort"):
                    break
        finally:
            state.flow_unsubscribe(q)

    return StreamingResponse(_generator(), media_type="text/event-stream")


@router.get("/api/flow/snapshots")
def flow_snapshots() -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_snapshots is None:
        return JSONResponse([])

    snaps = orch._current_snapshots.list()
    return JSONResponse([
        {
            "snapshot_id": s.snapshot_id,
            "plan_id": s.plan_id,
            "flow_id": s.plan_id,
            "timestamp": s.timestamp,
            "trigger": s.trigger,
            "cycle": s.cycle,
        }
        for s in snaps
    ])


@router.post("/api/flow/rollback")
def flow_rollback(req: RollbackRequest) -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_snapshots is None:
        return JSONResponse({"error": "No active flow"}, status_code=400)

    new_doc = orch._current_snapshots.rollback(req.snapshot_id)
    orch._current_doc = new_doc
    return JSONResponse({"status": "ok", "snapshot_id": req.snapshot_id})


@router.get("/api/flow/logs")
async def flow_logs(n: int = 100, task_id: str | None = None) -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_logger is None:
        return JSONResponse([])

    from agent.flow.log import LogLevel
    records = await orch._current_logger.read_async(
        level_min=LogLevel.DEBUG,
        task_id=task_id or None,
        n=n,
    )
    return JSONResponse(records)


@router.post("/api/flow/pause")
def flow_pause() -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_doc is None:
        return JSONResponse({"error": "No active flow"}, status_code=400)
    orch._current_doc.pause()
    return JSONResponse({"status": "paused"})


@router.post("/api/flow/resume")
def flow_resume() -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_doc is None:
        return JSONResponse({"error": "No active flow"}, status_code=400)
    orch._current_doc.resume()
    return JSONResponse({"status": "resumed"})


@router.get("/api/flow/task/{task_id}/steps")
def flow_task_steps(task_id: str) -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    steps = (orch._task_steps.get(task_id, []) if orch is not None else [])
    return JSONResponse({"task_id": task_id, "steps": steps})


@router.post("/api/flow/skip/{task_id}")
def flow_skip(task_id: str, req: SkipRequest = SkipRequest()) -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_doc is None:
        return JSONResponse({"error": "No active flow"}, status_code=400)
    orch._current_doc.skip(task_id, cascade=req.cascade)
    return JSONResponse({"status": "skipped", "task_id": task_id})


@router.patch("/api/flow/tasks/{task_id}")
async def flow_task_patch(task_id: str, req: TaskPatchRequest) -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_doc is None:
        return JSONResponse({"error": "No active flow"}, status_code=400)
    from agent.flow.document import TaskStatus
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
        state.flow_broadcast(_with_flow_id({"type": "task_updated", "task_id": task_id, "updates": updates}))
    return JSONResponse({"status": "ok", "task_id": task_id, "updates": updates})


@router.post("/api/flow/human-request")
async def flow_human_request(req: HumanMessageRequest) -> JSONResponse:
    state = get_state()
    orch = state.active_orchestrator
    if orch is None or orch._current_doc is None:
        return JSONResponse({"error": "No active flow"}, status_code=400)
    logger = orch._current_logger
    snapshots = orch._current_snapshots
    plan_id = orch.current_plan_id or ""
    if logger and snapshots:
        await orch._call_replanner(
            orch._current_doc, snapshots, logger, plan_id, trigger="on_human_request"
        )
    state.flow_broadcast(_with_flow_id({"type": "human_request_received", "message": req.message}))
    return JSONResponse({"status": "ok", "message": "Human request forwarded to replanner."})


def _get_history_store():
    from agent.flow.history import PlanHistoryStore
    from config import paths
    history_dir = Path(paths.cache_root) / "plans" / "history"
    return PlanHistoryStore(str(history_dir))


@router.get("/api/flow/history")
def flow_history_list() -> JSONResponse:
    store = _get_history_store()
    return JSONResponse(store.list_all())


@router.delete("/api/flow/history/{plan_id}")
def flow_history_delete(plan_id: str) -> JSONResponse:
    store = _get_history_store()
    store.delete(plan_id)
    return JSONResponse({"status": "deleted", "plan_id": plan_id})
