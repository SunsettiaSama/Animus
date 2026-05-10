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

def _sub_event_to_dict(event) -> dict | None:
    from agent.react.tao import (
        SubAgentStartEvent,
        SubAgentChunkEvent,
        SubAgentStepEvent,
        SubAgentFinishEvent,
        SubAgentErrorEvent,
    )
    if isinstance(event, SubAgentStartEvent):
        return {"type": "sub_start", "action": event.action, "instruction": event.instruction}
    if isinstance(event, SubAgentChunkEvent):
        return {"type": "sub_chunk", "index": event.index, "chunk": event.chunk}
    if isinstance(event, SubAgentStepEvent):
        return {
            "type": "sub_step",
            "index": event.index,
            "thought": event.thought,
            "action": event.action,
            "action_input": event.action_input,
            "observation": event.observation,
            "is_error": event.is_error,
        }
    if isinstance(event, SubAgentFinishEvent):
        return {"type": "sub_finish", "answer": event.answer}
    if isinstance(event, SubAgentErrorEvent):
        return {"type": "sub_error", "error": event.error}
    return None


def _event_to_dict(event) -> dict | None:
    from agent.react.tao import (
        ApprovalRequestEvent,
        ChunkEvent,
        FinishEvent,
        MaxStepsEvent,
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
            "calls": event.calls,    # list[{action, args}] | None — parallel calls
            "output": event.output,  # <O> content; empty string when absent
        }
    if isinstance(event, FinishEvent):
        return {"type": "finish", "answer": event.answer}
    if isinstance(event, MaxStepsEvent):
        return {"type": "max_steps", "max_steps": event.max_steps}
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
    return _sub_event_to_dict(event)


# ── Notification helper ───────────────────────────────────────────────────────

def _push_notify(state, task: str, message: str, done: bool = False) -> None:
    """Thread-safe push of a notification event to the SSE notify queue."""
    if state.notify_queue is None or state.main_event_loop is None:
        return
    item = {"type": "notify", "task": task, "message": message, "done": done}
    state.main_event_loop.call_soon_threadsafe(state.notify_queue.put_nowait, item)


# ── ReAct init ────────────────────────────────────────────────────────────────

def _do_react_init(req: ReactInitRequest, state) -> None:
    """Background worker that builds TaoLoop and ConvLoop."""
    from agent.react.factory import build_conv_loop

    # Wait for any in-flight preload to finish, then release its QdrantClient
    # file lock before we create a new one.
    old_preload = state.preload_future
    old_tao     = state.active_tao
    if old_preload is not None and not old_preload.done():
        old_preload.result(timeout=120)
    if old_tao is not None:
        old_tao.close()

    conv_loop = build_conv_loop(
        state,
        lang=req.lang,
        max_steps=req.max_steps,
        primary_tools=req.primary_tools,
        enable_kb=req.enable_kb,
        reply_target={"type": "webui"},
    )
    tao = conv_loop._tao
    state.active_tao = tao
    state.conv_loop  = conv_loop
    state.react_init_event.set()

    # Wire plan event_sink: when the agent triggers run_plan via chat, plan events
    # are broadcast to all active SSE subscribers via state.plan_broadcast().
    def _make_plan_sink(st):
        def _sink(event_dict: dict) -> None:
            loop = st.main_event_loop
            if loop is None:
                return
            loop.call_soon_threadsafe(st.plan_broadcast, event_dict)
        return _sink

    tao.set_plan_event_sink(_make_plan_sink(state))

    def _preload_with_notify():
        _push_notify(state, "preload", "正在加载嵌入模型与长期记忆…", done=False)
        tao.preload()
        _push_notify(state, "preload", "嵌入模型与长期记忆已就绪", done=True)

    state.preload_future = state.task_runner.submit("preload", _preload_with_notify)




@router.post("/api/react/init")
@router.post("/api/react/reinit")
def react_init(req: ReactInitRequest):
    state = get_state()
    if state.llm_service is None or state.llm_service.handle is None:
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
    if state.react_init_error:
        return {"status": "error", "detail": state.react_init_error}
    if state.conv_loop is None:
        if not state.react_init_event.is_set():
            return {"status": "initializing"}
        return {"status": "not_initialized"}
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


# ── Notification SSE endpoint ─────────────────────────────────────────────────

import json
from fastapi.responses import StreamingResponse as _SR

@router.get("/api/react/notify")
async def notify_stream():
    """Persistent SSE stream for background task notifications.

    Emits ``{"type":"notify","task":"...","message":"...","done":bool}`` events
    whenever a background task (preload, post_process) starts or finishes.
    """
    state = get_state()

    async def _generate():
        if state.notify_queue is None:
            return
        while True:
            item = await state.notify_queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

    return _SR(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── SSE legacy endpoint ────────────────────────────────────────────────────────

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

    # B2: atomic check-and-set — reject concurrent streams immediately.
    if not state.try_start_streaming(gen_id):
        await websocket.send_json({"type": "error", "message": "Already streaming."})
        await websocket.close()
        return

    # B4: get_running_loop() is the correct API inside a coroutine (3.10+).
    loop:  asyncio.AbstractEventLoop = asyncio.get_running_loop()
    queue: asyncio.Queue             = asyncio.Queue()

    def _produce():
        if state.active_tao is not None:
            state.active_tao.sub_event_sink = lambda ev: (
                (msg := _sub_event_to_dict(ev)) and
                loop.call_soon_threadsafe(queue.put_nowait, msg)
            )

        # Chunk batching: accumulate consecutive ChunkEvents from the same step
        # and flush every _CHUNK_FLUSH_N tokens so the frontend receives progressive
        # updates rather than one giant frame per step.  Step boundaries always
        # force a flush regardless of buffer size.
        _CHUNK_FLUSH_N  = 4
        _chunk_buf: list[str] = []
        _chunk_idx: int = -1

        def _flush_chunks() -> None:
            nonlocal _chunk_buf, _chunk_idx
            if _chunk_buf:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    {"type": "chunk", "index": _chunk_idx, "chunk": "".join(_chunk_buf)},
                )
                _chunk_buf = []
                _chunk_idx = -1

        from agent.react.tao import ChunkEvent
        for event in state.conv_loop.stream(question):
            if isinstance(event, ChunkEvent):
                if event.index != _chunk_idx:
                    _flush_chunks()
                    _chunk_idx = event.index
                _chunk_buf.append(event.chunk)
                if len(_chunk_buf) >= _CHUNK_FLUSH_N:
                    _flush_chunks()
            else:
                _flush_chunks()
                msg = _event_to_dict(event)
                if msg:
                    loop.call_soon_threadsafe(queue.put_nowait, msg)

        _flush_chunks()
        if state.active_tao is not None:
            state.active_tao.sub_event_sink = None
        loop.call_soon_threadsafe(queue.put_nowait, None)

    def _on_produce_error(exc: BaseException) -> None:
        if state.active_tao is not None:
            state.active_tao.sub_event_sink = None
        loop.call_soon_threadsafe(
            queue.put_nowait, {"type": "error", "message": str(exc)}
        )
        loop.call_soon_threadsafe(queue.put_nowait, None)

    # B2: task name includes gen_id to avoid name collisions if a connection
    # somehow overlaps (defense in depth on top of the try_start_streaming gate).
    state.task_runner.submit(f"ws_produce_{gen_id}", _produce, on_error=_on_produce_error)

    # B3: wrap _receive_client in try/except so WebSocketDisconnect and other
    # transport errors are silently absorbed — the producer thread handles cleanup.
    async def _receive_client():
        try:
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
        except Exception:
            pass  # WebSocketDisconnect or connection drop — handled by producer

    receive_task = asyncio.create_task(_receive_client())

    while True:
        item = await queue.get()
        if item is None:
            break
        await websocket.send_json(item)
        # Yield to the event loop so each chunk frame is flushed individually
        # rather than batched.  Without this, the asyncio event loop drains the
        # entire queue before doing I/O polling, causing all chunks to arrive at
        # the browser simultaneously (single-step responses appear non-streaming).
        if item.get("type") == "chunk":
            await asyncio.sleep(0)

    receive_task.cancel()
    # Await the cancelled task so its CancelledError is retrieved and the
    # "Task exception was never retrieved" warning is suppressed.
    try:
        await receive_task
    except (asyncio.CancelledError, Exception):
        pass

    was_aborted = (
        state.conv_loop is not None
        and state.conv_loop._tao._stop_event.is_set()
    )
    if was_aborted:
        state.conv_loop._tao.rollback_turn()
        await websocket.send_json({"type": "finish", "answer": "", "aborted": True})
    else:
        if state.conv_loop is not None:
            _conv_loop = state.conv_loop
            def _post_process_with_notify():
                _push_notify(state, "post_process", "正在写入记忆…", done=False)
                _conv_loop.post_process()
                _push_notify(state, "post_process", "记忆写入完成", done=True)
            state.task_runner.submit("post_process", _post_process_with_notify)

    state.set_streaming(False)
    await websocket.close()
