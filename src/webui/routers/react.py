from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, WebSocket
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from state import get_state

router = APIRouter()


# ── Request models ────────────────────────────────────────────────────────────

class ReactInitRequest(BaseModel):
    lang: str = "cn"
    max_steps: int = 10
    primary_tools: list[str] | None = None
    enable_kb: bool = False


class ReactRunRequest(BaseModel):
    question: str


class RestoreRequest(BaseModel):
    messages: list[dict]


# ── Helper: serialise TaoEvents to wire dict ───────────────────────────────────

def _event_to_dict(event) -> dict | None:
    from react.tao import (
        ApprovalRequestEvent,
        ChunkEvent,
        FinishEvent,
        PromptPreviewEvent,
        RetryEvent,
        StepEvent,
        StepStartEvent,
    )
    if isinstance(event, PromptPreviewEvent):
        return {"type": "prompt_preview", "messages": event.messages}
    if isinstance(event, StepStartEvent):
        return {"type": "step_start", "index": event.index}
    if isinstance(event, RetryEvent):
        return {"type": "retry", "index": event.index, "reason": event.reason}
    if isinstance(event, ChunkEvent):
        return {"type": "chunk", "index": event.index, "chunk": event.chunk}
    if isinstance(event, StepEvent):
        return {
            "type": "step",
            "index": event.index,
            "thought": event.thought,
            "action": event.action,
            "action_input": event.action_input,
            "observation": event.observation,
        }
    if isinstance(event, FinishEvent):
        return {"type": "finish", "answer": event.answer}
    if isinstance(event, ApprovalRequestEvent):
        return {
            "type": "approval_request",
            "request_id": event.request_id,
            "tool_name": event.tool_name,
            "args": event.args,
            "risk_level": event.risk_level,
            "reason": event.reason,
            "deadline_secs": event.deadline_secs,
        }
    return None


# ── ReAct init ────────────────────────────────────────────────────────────────

def _do_react_init(req: ReactInitRequest, state) -> None:
    """Background worker that builds TaoLoop and ConvLoop."""
    from config.react.tao_config import TaoConfig
    from config.react.prompt_config import PromptConfig
    from config.react.memory.memory_config import MemoryConfig
    from config.react.persona_config import PersonaConfig
    from scheduler import SchedulerConfig
    from crew import CrewConfig
    from react.loop import ConvLoop
    from react.tao import TaoLoop

    def _load_memory_config() -> MemoryConfig:
        if os.path.exists(state.memory_config_yaml):
            return MemoryConfig.from_yaml(state.memory_config_yaml)
        return MemoryConfig()

    def _load_persona_config() -> PersonaConfig:
        import json
        d: dict = {}
        if os.path.exists(state.persona_cfg_file):
            with open(state.persona_cfg_file, encoding="utf-8") as fh:
                d = json.load(fh)
        return PersonaConfig(
            enabled=d.get("enabled", False),
            persona_dir=state.persona_dir,
            max_profile_chars=d.get("max_profile_chars", 500),
            evolution_enabled=d.get("evolution_enabled", False),
            evolve_interval=d.get("evolve_interval", 1),
            skills_enabled=d.get("skills_enabled", True),
            max_skills_in_prompt=d.get("max_skills_in_prompt", 5),
            max_skills_chars=d.get("max_skills_chars", 600),
            reflection_enabled=d.get("reflection_enabled", False),
            reflect_interval=d.get("reflect_interval", 3),
            max_reflection_chars=d.get("max_reflection_chars", 400),
        )

    # Cancel any running scheduler from a previous init.
    if state.scheduler_future is not None and not state.scheduler_future.done():
        state.scheduler_future.cancel()
    state.scheduler_future = None

    # Wait for any in-flight preload to finish, then release its QdrantClient
    # file lock before we create a new one.
    old_preload = state.preload_future
    old_tao     = state.active_tao
    if old_preload is not None and not old_preload.done():
        old_preload.result(timeout=120)
    if old_tao is not None:
        old_tao.close()

    executor          = state.tool_manager.build_executor()
    tool_descriptions = state.tool_manager.primary_descriptions(req.primary_tools)
    category_summary  = state.tool_manager.category_summary()

    cfg = TaoConfig(
        max_steps=req.max_steps,
        storage=state.cache,
        prompt=PromptConfig(lang=req.lang),
        memory=_load_memory_config(),
        persona=_load_persona_config(),
        knowledge=state.kb_cfg if req.enable_kb else None,
        scheduler=SchedulerConfig(
            scheduler_dir=state.cache.scheduler_dir,
            llm_cfg_path=state.llm_config_yaml,
        ),
        crew=CrewConfig(llm_cfg_path=state.llm_config_yaml),
    )

    tao = None
    from config.react.risk_config import RiskConfig
    from react.action.risk.gate import RiskGate
    risk_gate = RiskGate.from_config(RiskConfig())

    tao = TaoLoop(
        llm=state.llm,
        executor=executor,
        tool_descriptions=tool_descriptions,
        cfg=cfg,
        tool_category_summary=category_summary,
        sandbox=state.sandbox_manager,
        risk_gate=risk_gate,
    )
    state.active_tao = tao
    state.conv_loop  = ConvLoop(tao)
    state.react_init_event.set()

    state.preload_future = state.task_runner.submit("preload", tao.preload)

    if tao.scheduler_engine is not None and state.main_event_loop is not None:
        state.scheduler_future = asyncio.run_coroutine_threadsafe(
            tao.scheduler_engine.start(), state.main_event_loop
        )


@router.post("/api/react/init")
@router.post("/api/react/reinit")
def react_init(req: ReactInitRequest):
    state = get_state()
    if state.llm is None:
        return JSONResponse(status_code=400, content={"error": "LLM not initialized."})
    if state.is_streaming:
        return JSONResponse(
            status_code=409,
            content={"error": "Cannot reinitialize while streaming is active."},
        )
    if req.primary_tools is not None:
        unknown = [n for n in req.primary_tools if n not in state.tool_manager.registry]
        if unknown:
            return JSONResponse(status_code=400, content={"error": f"Unknown tools: {unknown}"})

    state.prompt_lang = req.lang
    state.react_init_event.clear()
    state.react_init_error = ""
    state.conv_loop = None

    def _run():
        _do_react_init(req, state)

    def _on_error(exc: BaseException) -> None:
        state.react_init_error = str(exc)
        state.react_init_event.set()

    state.task_runner.submit("react_init", _run, on_error=_on_error)
    return {"status": "initializing"}


@router.get("/api/react/status")
def react_status():
    state = get_state()
    if not state.react_init_event.is_set():
        return {"status": "initializing"}
    if state.react_init_error:
        return {"status": "error", "detail": state.react_init_error}
    return {"status": "ready", "is_streaming": state.is_streaming}


@router.post("/api/react/restore")
def react_restore(req: RestoreRequest):
    state = get_state()
    if state.conv_loop is None:
        return JSONResponse(status_code=400, content={"error": "ReAct not initialized."})
    state.conv_loop.restore(req.messages)
    return {"status": "ok", "turn_count": state.conv_loop.turn_count}


@router.post("/api/react/reset")
def react_reset():
    state = get_state()
    if state.conv_loop is None:
        return JSONResponse(status_code=400, content={"error": "ReAct not initialized."})
    state.conv_loop.reset()
    return {"status": "ok"}


@router.post("/api/react/abort")
def react_abort():
    """REST fallback abort (e.g. when WS is lost due to page reload)."""
    state = get_state()
    if state.active_tao is not None:
        state.active_tao.abort()
    state.set_streaming(False)
    return {"status": "ok"}


@router.post("/api/react/memory/clear")
def react_memory_clear():
    state = get_state()
    if state.conv_loop is None:
        return JSONResponse(status_code=400, content={"error": "ReAct not initialized."})
    state.conv_loop._tao.clear_memory()
    return {"status": "ok", "message": "所有记忆已清空。"}


@router.post("/api/react/persona/clear")
def react_persona_clear():
    state = get_state()
    if state.conv_loop is None:
        return JSONResponse(status_code=400, content={"error": "ReAct not initialized."})
    if state.conv_loop._tao._persona is None:
        return JSONResponse(status_code=400, content={"error": "Persona not enabled."})
    state.conv_loop._tao.clear_persona()
    return {"status": "ok", "message": "人格漂移数据已清空。"}


@router.get("/api/timeline")
def get_timeline(date: str | None = None):
    state = get_state()
    if state.active_tao is None:
        return {"events": []}
    return {"events": state.active_tao.timeline.read(date=date)}


@router.get("/api/react/tools")
def react_tools():
    state = get_state()
    by_category: dict[str, list[dict]] = {}
    for info in state.tool_manager.all_tool_info():
        by_category.setdefault(info["category"], []).append(info)
    return {
        "total":       len(state.tool_manager.registry),
        "primary":     state.tool_manager.primary_names,
        "by_category": by_category,
    }


@router.get("/api/react/tools/search")
def react_tools_search(query: str, top_k: int = 5):
    state = get_state()
    results = state.tool_manager.search(query, top_k)
    return {
        "query": query,
        "results": [
            {"name": m.name, "description": m.description, "category": m.category}
            for m in results
        ],
    }


# ── SSE legacy endpoint ────────────────────────────────────────────────────────

import json
from fastapi.responses import StreamingResponse as _SR

@router.post("/api/react/run")
def react_run(req: ReactRunRequest):
    state = get_state()
    if state.conv_loop is None:
        return JSONResponse(status_code=400, content={"error": "ReAct not initialized."})

    def generate():
        for event in state.conv_loop.stream(req.question):
            msg = _event_to_dict(event)
            if msg:
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
        state.conv_loop.post_process()

    return _SR(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── WebSocket endpoint (new protocol with gen_id + abort) ─────────────────────

@router.websocket("/ws/react/run")
async def ws_react_run(websocket: WebSocket):
    state = get_state()
    await websocket.accept()
    data     = await websocket.receive_json()
    question = data.get("question", "")
    gen_id   = data.get("gen_id", "")

    if state.conv_loop is None:
        await websocket.send_json({"type": "error", "message": "ReAct not initialized."})
        await websocket.close()
        return

    state.set_streaming(True, gen_id)

    loop:  asyncio.AbstractEventLoop = asyncio.get_event_loop()
    queue: asyncio.Queue             = asyncio.Queue()

    def _produce():
        for event in state.conv_loop.stream(question):
            msg = _event_to_dict(event)
            if msg:
                loop.call_soon_threadsafe(queue.put_nowait, msg)
        loop.call_soon_threadsafe(queue.put_nowait, None)

    def _on_produce_error(exc: BaseException) -> None:
        loop.call_soon_threadsafe(
            queue.put_nowait, {"type": "error", "message": str(exc)}
        )
        loop.call_soon_threadsafe(queue.put_nowait, None)

    state.task_runner.submit("ws_react_produce", _produce, on_error=_on_produce_error)

    async def _receive_client():
        while True:
            msg = await websocket.receive_json()
            mtype = msg.get("type")
            if mtype == "approval_response" and state.conv_loop is not None:
                state.conv_loop._tao.resolve_approval(
                    msg.get("request_id", ""),
                    bool(msg.get("approved", False)),
                )
            elif mtype == "abort":
                if msg.get("gen_id") == state.current_gen_id:
                    if state.conv_loop is not None:
                        state.conv_loop._tao.abort()

    receive_task = asyncio.create_task(_receive_client())

    while True:
        item = await queue.get()
        if item is None:
            break
        await websocket.send_json(item)

    receive_task.cancel()

    was_aborted = (
        state.conv_loop is not None
        and state.conv_loop._tao._stop_event.is_set()
    )
    if was_aborted:
        state.conv_loop._tao.rollback_turn()
        await websocket.send_json({"type": "finish", "answer": "", "aborted": True})
    else:
        if state.conv_loop is not None:
            state.task_runner.submit("post_process", state.conv_loop.post_process)

    state.set_streaming(False)
    await websocket.close()
