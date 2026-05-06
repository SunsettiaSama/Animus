from __future__ import annotations

import json
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from state import get_state

router = APIRouter()


# ── WebUI settings helpers ────────────────────────────────────────────────────

_WEBUI_DEFAULTS: dict = {
    "tools_enabled":    False,
    "show_full_prompt": False,
    "prompt_lang":      "cn",
    "max_steps":        10,
}


def _load_webui_settings(path: str) -> dict:
    if not os.path.exists(path):
        return dict(_WEBUI_DEFAULTS)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {k: data.get(k, v) for k, v in _WEBUI_DEFAULTS.items()}


def _save_webui_settings(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── Request models ────────────────────────────────────────────────────────────

class InitRequest(BaseModel):
    model: str
    api_key: str = ""
    base_url: str | None = None
    max_tokens: int = 512
    temperature: float = 1.0
    do_sample: bool = False
    top_p: float = 1.0
    top_k: int = 0
    repetition_penalty: float = 1.0
    device: str = "auto"
    system_prompt: str = ""
    backend: str = "openai"


class PatchLLMRequest(BaseModel):
    """Hot-swap LLM handle without rebuilding TaoLoop/ConvLoop."""
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    do_sample: bool | None = None
    top_p: float | None = None
    top_k: int | None = None
    repetition_penalty: float | None = None
    device: str | None = None
    system_prompt: str | None = None
    backend: str | None = None


class SaveConfigRequest(BaseModel):
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    max_tokens: int = 512
    temperature: float = 1.0
    do_sample: bool = False
    device: str = "auto"
    system_prompt: str = ""
    # WebUI preference fields (stored separately in config/webui/settings.json)
    tools_enabled: bool = False
    show_full_prompt: bool = False
    prompt_lang: str = "cn"
    max_steps: int = 10


# ── LLM config ────────────────────────────────────────────────────────────────

@router.get("/api/config")
@router.get("/api/llm/config")
def get_config():
    state = get_state()
    llm_fields: dict = {}
    if state.llm_cfg is not None:
        llm_fields = {
            "model":         state.llm_cfg.model,
            "api_key":       state.llm_cfg.api_key,
            "base_url":      state.llm_cfg.base_url or "",
            "max_tokens":    state.llm_cfg.max_tokens,
            "temperature":   state.llm_cfg.temperature,
            "do_sample":     state.llm_cfg.do_sample,
            "device":        state.llm_cfg.device,
            "system_prompt": state.llm_cfg.system_prompt,
            "backend":       getattr(state.llm_cfg, "backend", "openai"),
        }
    webui_fields = _load_webui_settings(state.webui_settings_json)
    return {**llm_fields, **webui_fields}


@router.post("/api/config/save")
def save_config(req: SaveConfigRequest):
    import yaml
    state = get_state()
    os.makedirs(os.path.dirname(state.llm_config_yaml), exist_ok=True)
    data = {
        "model":         req.model,
        "api_key":       req.api_key,
        "base_url":      req.base_url or "",
        "max_tokens":    req.max_tokens,
        "temperature":   req.temperature,
        "do_sample":     req.do_sample,
        "device":        req.device,
        "system_prompt": req.system_prompt or "",
    }
    with open(state.llm_config_yaml, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    _save_webui_settings(state.webui_settings_json, {
        "tools_enabled":    req.tools_enabled,
        "show_full_prompt": req.show_full_prompt,
        "prompt_lang":      req.prompt_lang,
        "max_steps":        req.max_steps,
    })
    return {"status": "ok"}


# ── LLM init / hot-swap ───────────────────────────────────────────────────────

@router.post("/api/init")
@router.post("/api/llm/init")
def init_llm(req: InitRequest):
    from config.llm_core.config import LLMConfig
    state = get_state()
    cfg = LLMConfig(
        model=req.model,
        api_key=req.api_key,
        base_url=req.base_url,
        max_tokens=req.max_tokens,
        temperature=req.temperature,
        do_sample=req.do_sample,
        top_p=req.top_p,
        top_k=req.top_k,
        repetition_penalty=req.repetition_penalty,
        device=req.device,
        system_prompt=req.system_prompt,
        backend=req.backend,
    )
    state.llm_service.start(cfg)
    return {"status": "ok", "backend": req.backend}


@router.patch("/api/llm")
def patch_llm(req: PatchLLMRequest):
    """Hot-swap LLM handle only; refuse if a stream is in progress."""
    from config.llm_core.config import LLMConfig
    state = get_state()
    if state.is_streaming:
        return JSONResponse(
            status_code=409,
            content={"error": "Cannot modify LLM while streaming is active."},
        )
    if state.llm_cfg is None:
        return JSONResponse(status_code=400, content={"error": "LLM not initialized."})
    old = state.llm_cfg
    cfg = LLMConfig(
        model=req.model if req.model is not None else old.model,
        api_key=req.api_key if req.api_key is not None else old.api_key,
        base_url=req.base_url if req.base_url is not None else old.base_url,
        max_tokens=req.max_tokens if req.max_tokens is not None else old.max_tokens,
        temperature=req.temperature if req.temperature is not None else old.temperature,
        do_sample=req.do_sample if req.do_sample is not None else old.do_sample,
        top_p=req.top_p if req.top_p is not None else getattr(old, "top_p", 1.0),
        top_k=req.top_k if req.top_k is not None else getattr(old, "top_k", 0),
        repetition_penalty=req.repetition_penalty if req.repetition_penalty is not None else getattr(old, "repetition_penalty", 1.0),
        device=req.device if req.device is not None else old.device,
        system_prompt=req.system_prompt if req.system_prompt is not None else old.system_prompt,
        backend=req.backend if req.backend is not None else getattr(old, "backend", "openai"),
    )
    state.llm_service.reload(cfg)
    return {"status": "ok"}


# ── Status ────────────────────────────────────────────────────────────────────

@router.get("/api/status")
def status():
    state = get_state()
    turn_count = state.conv_loop.turn_count if state.conv_loop is not None else 0
    initialized = state.llm is not None
    return {
        "initialized":     initialized,
        "llm_initialized": initialized,   # alias kept for forward-compat
        "model":           state.llm_cfg.model if state.llm_cfg else None,
        "backend":         getattr(state.llm_cfg, "backend", None) if state.llm_cfg else None,
        "react_ready":     state.conv_loop is not None,
        "turn_count":      turn_count,
        "is_streaming":    state.is_streaming,
    }


