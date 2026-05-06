from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from state import get_state

router = APIRouter(prefix="/api/bot", tags=["bot"])


# ── Config models ─────────────────────────────────────────────────────────────

class BotConfigPayload(BaseModel):
    ws_url:                  str       = "ws://127.0.0.1:3001"
    access_token:            str       = ""
    reconnect_interval_sec:  float     = 5.0
    allowed_private_users:   list[int] = []
    allowed_groups:          list[int] = []
    command_prefix:          str       = ""
    max_sessions:            int       = 100
    session_ttl_hours:       float     = 24.0


@router.get("/config")
def get_bot_config():
    from config.infra.bot_config import BotConfig
    cfg = BotConfig.load()
    return {
        "ws_url":                 cfg.ws_url,
        "access_token":           cfg.access_token,
        "reconnect_interval_sec": cfg.reconnect_interval_sec,
        "allowed_private_users":  cfg.allowed_private_users,
        "allowed_groups":         cfg.allowed_groups,
        "command_prefix":         cfg.command_prefix,
        "max_sessions":           cfg.max_sessions,
        "session_ttl_hours":      cfg.session_ttl_hours,
    }


@router.post("/config/save")
def save_bot_config(req: BotConfigPayload):
    from config.infra.bot_config import BotConfig
    from config import paths as app_paths
    state   = get_state()
    new_cfg = BotConfig(
        ws_url=req.ws_url,
        access_token=req.access_token,
        reconnect_interval_sec=req.reconnect_interval_sec,
        allowed_private_users=req.allowed_private_users,
        allowed_groups=req.allowed_groups,
        command_prefix=req.command_prefix,
        max_sessions=req.max_sessions,
        session_ttl_hours=req.session_ttl_hours,
    )
    new_cfg.to_yaml(app_paths.bot_config_yaml)
    # Push live changes to the running service
    if state.bot_service is not None:
        state.bot_service._cfg = new_cfg
    return {"status": "ok"}


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
