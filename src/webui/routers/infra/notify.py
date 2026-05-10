from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from state import get_state

router = APIRouter(prefix="/api/notify", tags=["notify"])


# ── Pydantic 请求体 ────────────────────────────────────────────────────────────

class BarkConfigPayload(BaseModel):
    enabled:    bool  = False
    server_url: str   = "https://api.day.app"
    device_key: str   = ""
    sound:      str   = ""
    group:      str   = "ReAct"


class NtfyConfigPayload(BaseModel):
    enabled:    bool  = False
    server_url: str   = "https://ntfy.sh"
    topic:      str   = ""
    username:   str   = ""
    password:   str   = ""
    priority:   int   = 3


# ── Bark endpoints ────────────────────────────────────────────────────────────

@router.get("/bark/config")
def get_bark_config():
    from config.infra.bark_config import BarkConfig
    cfg = BarkConfig.load()
    return {
        "enabled":    cfg.enabled,
        "server_url": cfg.server_url,
        "device_key": cfg.device_key,
        "sound":      cfg.sound,
        "group":      cfg.group,
    }


@router.post("/bark/config")
def save_bark_config(req: BarkConfigPayload):
    from config.infra.bark_config import BarkConfig
    from config import paths

    new_cfg = BarkConfig(
        enabled=req.enabled,
        server_url=req.server_url,
        device_key=req.device_key,
        sound=req.sound,
        group=req.group,
    )
    new_cfg.to_yaml(paths.bark_config_yaml)

    state = get_state()
    if state.bark_notifier is not None:
        state.bark_notifier.update(new_cfg)

    return {"status": "ok"}


@router.post("/bark/test")
def test_bark():
    state = get_state()
    if state.bark_notifier is None:
        return JSONResponse(status_code=503, content={"error": "BarkNotifier not initialized"})
    cfg = state.bark_notifier._cfg
    if not cfg.enabled:
        return JSONResponse(status_code=400, content={"error": "Bark is disabled"})
    if not cfg.device_key:
        return JSONResponse(status_code=400, content={"error": "device_key is not set"})
    try:
        state.bark_notifier.send("ReAct 测试通知", "Bark 通知渠道连接正常 ✓")
        return {"status": "ok"}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})


# ── ntfy endpoints ────────────────────────────────────────────────────────────

@router.get("/ntfy/config")
def get_ntfy_config():
    from config.infra.ntfy_config import NtfyConfig
    cfg = NtfyConfig.load()
    return {
        "enabled":    cfg.enabled,
        "server_url": cfg.server_url,
        "topic":      cfg.topic,
        "username":   cfg.username,
        "password":   cfg.password,
        "priority":   cfg.priority,
    }


@router.post("/ntfy/config")
def save_ntfy_config(req: NtfyConfigPayload):
    from config.infra.ntfy_config import NtfyConfig
    from config import paths

    new_cfg = NtfyConfig(
        enabled=req.enabled,
        server_url=req.server_url,
        topic=req.topic,
        username=req.username,
        password=req.password,
        priority=req.priority,
    )
    new_cfg.to_yaml(paths.ntfy_config_yaml)

    state = get_state()
    if state.ntfy_notifier is not None:
        state.ntfy_notifier.update(new_cfg)

    return {"status": "ok"}


@router.post("/ntfy/test")
def test_ntfy():
    state = get_state()
    if state.ntfy_notifier is None:
        return JSONResponse(status_code=503, content={"error": "NtfyNotifier not initialized"})
    cfg = state.ntfy_notifier._cfg
    if not cfg.enabled:
        return JSONResponse(status_code=400, content={"error": "ntfy is disabled"})
    if not cfg.topic:
        return JSONResponse(status_code=400, content={"error": "topic is not set"})
    try:
        state.ntfy_notifier.send("ReAct 测试通知", "ntfy 通知渠道连接正常 ✓")
        return {"status": "ok"}
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": str(exc)})
