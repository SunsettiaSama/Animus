from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from state import get_state

router = APIRouter(prefix="/api/bot", tags=["bot"])


# ── Config models ─────────────────────────────────────────────────────────────

class BotConfigPayload(BaseModel):
    enabled:                 bool      = False
    transport:               str       = "forward_ws"
    ws_url:                  str       = "ws://127.0.0.1:3001"
    access_token:            str       = ""
    reconnect_interval_sec:  float     = 5.0
    appid:                   str       = ""
    secret:                  str       = ""
    is_sandbox:              bool      = False
    allowed_private_users:   list[str] = []
    allowed_groups:          list[str] = []
    command_prefix:          str       = ""
    max_sessions:            int       = 100
    session_ttl_hours:       float     = 24.0
    invite_code:             str       = ""
    invite_daily_limit:      int       = 4

    # Accept both string and integer items (old JS sent ints, new JS sends strings)
    @field_validator("allowed_private_users", "allowed_groups", mode="before")
    @classmethod
    def _coerce_to_str_list(cls, v: object) -> list[str]:
        if isinstance(v, list):
            return [str(x) for x in v if str(x).strip()]
        return []


@router.get("/config")
def get_bot_config():
    from config.infra.bot_config import BotConfig
    cfg = BotConfig.load()
    return {
        "enabled":                cfg.enabled,
        "transport":              cfg.transport,
        "ws_url":                 cfg.ws_url,
        "access_token":           cfg.access_token,
        "reconnect_interval_sec": cfg.reconnect_interval_sec,
        "appid":                  cfg.appid,
        "secret":                 cfg.secret,
        "is_sandbox":             cfg.is_sandbox,
        "allowed_private_users":  cfg.allowed_private_users,
        "allowed_groups":         cfg.allowed_groups,
        "command_prefix":         cfg.command_prefix,
        "max_sessions":           cfg.max_sessions,
        "session_ttl_hours":      cfg.session_ttl_hours,
        "invite_code":            cfg.invite_code,
        "invite_daily_limit":     cfg.invite_daily_limit,
    }


@router.post("/config/save")
def save_bot_config(req: BotConfigPayload):
    from config.infra.bot_config import BotConfig
    from config import paths as app_paths
    state   = get_state()
    new_cfg = BotConfig(
        enabled=req.enabled,
        transport=req.transport,
        ws_url=req.ws_url,
        access_token=req.access_token,
        reconnect_interval_sec=req.reconnect_interval_sec,
        appid=req.appid,
        secret=req.secret,
        is_sandbox=req.is_sandbox,
        allowed_private_users=req.allowed_private_users,
        allowed_groups=req.allowed_groups,
        command_prefix=req.command_prefix,
        max_sessions=req.max_sessions,
        session_ttl_hours=req.session_ttl_hours,
        invite_code=req.invite_code,
        invite_daily_limit=req.invite_daily_limit,
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
