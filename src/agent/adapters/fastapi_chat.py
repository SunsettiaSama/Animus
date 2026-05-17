"""闲聊路由：轻量 LLM 对话，无工具链，为后续灵魂心跳注入提供基础接口。

端点
----
GET  /api/chat/status          — 会话是否就绪
POST /api/chat/reset           — 清空对话历史
POST /api/chat/system-prompt   — 动态更新 system prompt
WS   /ws/chat/run              — 流式闲聊（flush 模式，chunk→finish）
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Callable

from fastapi import APIRouter, WebSocket
from fastapi.responses import JSONResponse

CHAT_SESSION_ID = "chat"


def create_chat_router(get_state: Callable[[], Any]) -> APIRouter:
    router = APIRouter()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _get_chat(state: Any):
        mgr = state.session_manager
        if mgr is None:
            return None
        return mgr.get(CHAT_SESSION_ID)

    # ── Status ────────────────────────────────────────────────────────────────

    @router.get("/api/chat/status")
    def chat_status() -> dict:
        state = get_state()
        if state.llm_service is None or state.llm_service.handle is None:
            return {"status": "no_llm"}
        session = _get_chat(state)
        return {"status": "ready" if session is not None else "not_initialized"}

    # ── Reset ─────────────────────────────────────────────────────────────────

    @router.post("/api/chat/reset")
    def chat_reset() -> dict | JSONResponse:
        state = get_state()
        session = _get_chat(state)
        if session is None:
            return JSONResponse(status_code=400, content={"error": "Chat not initialized."})
        session.reset()
        return {"status": "ok"}

    # ── System prompt ─────────────────────────────────────────────────────────

    @router.post("/api/chat/system-prompt")
    def chat_set_system_prompt(body: dict) -> dict | JSONResponse:
        state = get_state()
        session = _get_chat(state)
        if session is None:
            return JSONResponse(status_code=400, content={"error": "Chat not initialized."})
        text = body.get("text", "").strip()
        if not text:
            return JSONResponse(status_code=400, content={"error": "text is required."})
        session.set_system_prompt(text)
        return {"status": "ok"}

    # ── WebSocket 流式闲聊 ─────────────────────────────────────────────────────

    @router.websocket("/ws/chat/run")
    async def ws_chat_run(websocket: WebSocket) -> None:
        state = get_state()
        await websocket.accept()

        data = await websocket.receive_json()
        question = data.get("question", "").strip()
        gen_id   = data.get("gen_id", "")

        if not question:
            await websocket.send_json({"type": "error", "message": "question is empty."})
            await websocket.close()
            return

        # 懒初始化：LLM 就绪后自动建立 chat 会话
        session = _get_chat(state)
        if session is None:
            if state.llm_service is None or state.llm_service.handle is None:
                await websocket.send_json({"type": "error", "message": "LLM not ready."})
                await websocket.close()
                return
            session = _init_chat_session(state)

        from agent.session.request import TaoRequest

        req = TaoRequest(
            kind="user",
            session_id=CHAT_SESSION_ID,
            question=question,
            gen_id=gen_id,
            stream_mode="flush",
        )
        resp_q = state.session_manager.submit(req)

        async def _receive_client() -> None:
            try:
                while True:
                    msg = await websocket.receive_json()
                    if msg.get("type") == "abort":
                        session.abort()
            except Exception:
                pass

        receive_task = asyncio.create_task(_receive_client())

        try:
            while True:
                item = await asyncio.to_thread(resp_q.get)
                if item is None:
                    break
                await websocket.send_json(item)
                if item.get("type") == "chunk":
                    await asyncio.sleep(0)
        finally:
            receive_task.cancel()
            try:
                await receive_task
            except (asyncio.CancelledError, Exception):
                pass

        await websocket.close()

    return router


def _init_chat_session(state: Any):
    """懒建 ChatSession 并注册到 SessionManager。"""
    from agent.session.chat_session import ChatSession

    session = ChatSession(
        session_id=CHAT_SESSION_ID,
        llm=state.llm_service.handle,
    )
    state.session_manager.register(CHAT_SESSION_ID, session, replace=True)
    return session
