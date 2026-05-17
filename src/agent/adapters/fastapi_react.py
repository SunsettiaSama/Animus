from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from fastapi import APIRouter, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse

from agent.adapters.react_bridge import do_react_init, push_notify
from agent.adapters.react_schemas import ReactInitRequest, ReactRunRequest, RestoreRequest
from agent.adapters.webui_bridge import WEBUI_SESSION_ID, WebUIBridge
from agent.adapters.react_wire import wire_sink_for_sub_agent


def create_react_router(get_state: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    # ── Init ──────────────────────────────────────────────────────────────────

    @router.post("/api/react/init")
    @router.post("/api/react/reinit")
    def react_init(req: ReactInitRequest) -> dict | JSONResponse:
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

        def _run() -> None:
            do_react_init(req, state)

        def _on_error(exc: BaseException) -> None:
            state.react_init_error = str(exc)
            state.react_init_event.set()

        state.task_runner.submit("react_init", _run, on_error=_on_error)
        return {"status": "initializing"}

    # ── Status ────────────────────────────────────────────────────────────────

    @router.get("/api/react/status")
    def react_status() -> dict:
        state = get_state()
        return WebUIBridge(state).get_status()

    # ── Restore / Reset ───────────────────────────────────────────────────────

    @router.post("/api/react/restore")
    def react_restore(req: RestoreRequest) -> dict | JSONResponse:
        state = get_state()
        bridge = WebUIBridge(state)
        session = bridge.get_session()
        if session is None:
            return JSONResponse(status_code=400, content={"error": "ReAct not initialized."})
        session.restore(req.messages)
        return {"status": "ok", "turn_count": session.conv_loop.turn_count}

    @router.post("/api/react/reset")
    def react_reset() -> dict | JSONResponse:
        state = get_state()
        session = WebUIBridge(state).get_session()
        if session is None:
            return JSONResponse(status_code=400, content={"error": "ReAct not initialized."})
        session.reset()
        return {"status": "ok"}

    # ── Abort ─────────────────────────────────────────────────────────────────

    @router.post("/api/react/abort")
    def react_abort() -> dict:
        state = get_state()
        session = WebUIBridge(state).get_session()
        if session is not None:
            session.abort()
        state.set_streaming(False)
        return {"status": "ok"}

    # ── Memory / Persona ──────────────────────────────────────────────────────

    @router.post("/api/react/memory/clear")
    def react_memory_clear() -> dict | JSONResponse:
        state = get_state()
        session = WebUIBridge(state).get_session()
        if session is None:
            return JSONResponse(status_code=400, content={"error": "ReAct not initialized."})
        session.conv_loop.clear_persistent_memory()
        return {"status": "ok", "message": "所有记忆已清空。"}

    @router.post("/api/react/persona/clear")
    def react_persona_clear() -> dict | JSONResponse:
        state = get_state()
        session = WebUIBridge(state).get_session()
        if session is None:
            return JSONResponse(status_code=400, content={"error": "ReAct not initialized."})
        if not session.conv_loop.persona_enabled:
            return JSONResponse(status_code=400, content={"error": "Persona not enabled."})
        session.conv_loop.clear_persona()
        return {"status": "ok", "message": "人格漂移数据已清空。"}

    # ── Timeline ──────────────────────────────────────────────────────────────

    @router.get("/api/timeline")
    def get_timeline(date: str | None = None) -> dict:
        state = get_state()
        session = WebUIBridge(state).get_session()
        if session is not None:
            return {"events": session.conv_loop.read_timeline(date=date)}
        if state.active_tao is not None:
            return {"events": state.active_tao.timeline.read(date=date)}
        return {"events": []}

    # ── Tools ─────────────────────────────────────────────────────────────────

    @router.get("/api/react/tools")
    def react_tools() -> dict:
        state = get_state()
        by_category: dict[str, list[dict]] = {}
        for info in state.tool_manager.all_tool_info():
            by_category.setdefault(info["category"], []).append(info)
        return {
            "total": len(state.tool_manager.registry),
            "primary": state.tool_manager.primary_names,
            "by_category": by_category,
        }

    @router.get("/api/react/tools/search")
    def react_tools_search(query: str, top_k: int = 5) -> dict:
        state = get_state()
        results = state.tool_manager.search(query, top_k)
        return {
            "query": query,
            "results": [
                {"name": m.name, "description": m.description, "category": m.category}
                for m in results
            ],
        }

    # ── SSE notify stream ─────────────────────────────────────────────────────

    @router.get("/api/react/notify")
    async def notify_stream() -> StreamingResponse:
        state = get_state()

        async def _generate():
            if state.notify_queue is None:
                return
            while True:
                item = await state.notify_queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            _generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── SSE run（HTTP fallback，flush 模式）────────────────────────────────────

    @router.post("/api/react/run")
    def react_run(req: ReactRunRequest) -> StreamingResponse | JSONResponse:
        state = get_state()
        session = WebUIBridge(state).get_session()
        if session is None:
            return JSONResponse(status_code=400, content={"error": "ReAct not initialized."})

        from agent.session.request import TaoRequest
        from agent.adapters.react_stream import composer_for_mode

        tao_req = TaoRequest(
            kind="user",
            session_id=WEBUI_SESSION_ID,
            question=req.question,
            stream_mode=req.stream_mode,
        )
        resp_q = state.session_manager.submit(tao_req)

        def generate():
            while True:
                item = resp_q.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # ── WebSocket run（主通道，flush 推送）────────────────────────────────────

    @router.websocket("/ws/react/run")
    async def ws_react_run(websocket: WebSocket) -> None:
        state = get_state()
        await websocket.accept()

        data = await websocket.receive_json()
        question  = data.get("question", "")
        gen_id    = data.get("gen_id", "")
        raw_mode  = data.get("stream_mode", "flush")

        bridge = WebUIBridge(state)

        if not bridge.is_ready():
            await websocket.send_json({"type": "error", "message": "ReAct not initialized."})
            await websocket.close()
            return

        if not state.try_start_streaming(gen_id):
            await websocket.send_json({"type": "error", "message": "Already streaming."})
            await websocket.close()
            return

        # asyncio Queue 用于 flow 事件 fan-out（plan_broadcast 写入）
        flow_q: asyncio.Queue = asyncio.Queue()
        flow_detach = state.attach_reactive_ws_flow_queue(flow_q)

        session = bridge.get_session()

        async def _receive_client() -> None:
            """后台协程：处理客户端上行消息（abort / approval）。"""
            try:
                while True:
                    msg = await websocket.receive_json()
                    mtype = msg.get("type")
                    if mtype == "approval_response" and session is not None:
                        session.resolve_approval(
                            msg.get("request_id", ""),
                            bool(msg.get("approved", False)),
                        )
                    elif mtype == "abort":
                        if msg.get("gen_id") == state.current_gen_id and session is not None:
                            session.abort()
            except Exception:
                pass

        try:
            receive_task = asyncio.create_task(_receive_client())

            # 主流：从 bridge 异步迭代器读取事件
            stream_done = False
            stream_iter = bridge.stream_user_turn(question, gen_id, raw_mode).__aiter__()
            flow_none_pending = False

            while not stream_done:
                # 同时监听主流和 flow 侧通道，哪个先来发哪个
                stream_get = asyncio.ensure_future(stream_iter.__anext__())
                flow_get   = asyncio.ensure_future(flow_q.get())

                done, pending = await asyncio.wait(
                    {stream_get, flow_get},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for task in pending:
                    task.cancel()

                for task in done:
                    if task is stream_get:
                        try:
                            item = task.result()
                            await websocket.send_json(item)
                            if item.get("type") in ("chunk", "sub_chunk"):
                                await asyncio.sleep(0)
                        except StopAsyncIteration:
                            stream_done = True
                    elif task is flow_get:
                        try:
                            fitem = task.result()
                            if fitem is not None:
                                await websocket.send_json(fitem)
                        except Exception:
                            pass

            receive_task.cancel()
            try:
                await receive_task
            except (asyncio.CancelledError, Exception):
                pass

        finally:
            flow_detach()

        state.set_streaming(False)
        await websocket.close()

    # ── Session list（调试用）─────────────────────────────────────────────────

    @router.get("/api/react/sessions")
    def react_sessions() -> dict:
        state = get_state()
        mgr = state.session_manager
        return {
            "sessions": mgr.active_sessions if mgr is not None else [],
        }

    return router
