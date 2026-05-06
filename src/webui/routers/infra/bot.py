from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from state import get_state

router = APIRouter(prefix="/api/bot", tags=["bot"])


@router.get("/status")
def bot_status():
    state = get_state()
    if state.bot_service is None:
        return {"state": "unavailable"}
    return state.bot_service.status()


@router.get("/sessions")
def bot_sessions():
    state = get_state()
    if state.bot_service is None:
        return {"sessions": []}
    return {"sessions": state.bot_service.session_list()}


@router.post("/start")
def bot_start():
    state = get_state()
    if state.bot_service is None:
        return JSONResponse(status_code=503, content={"error": "BotService not initialized."})
    if state.llm_service is None or state.llm_service.handle is None:
        return JSONResponse(status_code=400, content={"error": "LLM not initialized."})
    state.bot_service.start()
    return {"status": "ok", **state.bot_service.status()}


@router.post("/stop")
def bot_stop():
    state = get_state()
    if state.bot_service is None:
        return JSONResponse(status_code=503, content={"error": "BotService not initialized."})
    state.bot_service.stop()
    return {"status": "ok"}
