from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from state import get_state

router = APIRouter()


class SandboxConfigPayload(BaseModel):
    workspace_root:          str       = ".react/workspace"
    python_timeout_secs:     int       = 10
    python_max_output_chars: int       = 5000
    python_blocked_modules:  list[str] = []
    http_allowed_domains:    list[str] = []
    http_blocked_domains:    list[str] = []
    max_file_size_bytes:     int       = 10_485_760


@router.get("/api/sandbox/config")
def get_sandbox_config():
    state = get_state()
    cfg   = state.sandbox_manager._cfg
    return JSONResponse({
        "workspace_root":          cfg.workspace_root,
        "python_timeout_secs":     cfg.python_timeout_secs,
        "python_max_output_chars": cfg.python_max_output_chars,
        "python_blocked_modules":  cfg.python_blocked_modules,
        "http_allowed_domains":    cfg.http_allowed_domains,
        "http_blocked_domains":    cfg.http_blocked_domains,
        "max_file_size_bytes":     cfg.max_file_size_bytes,
    })


@router.post("/api/sandbox/config/save")
def save_sandbox_config(req: SandboxConfigPayload):
    from config.infra.sandbox_config import SandboxConfig
    state = get_state()
    new_cfg = SandboxConfig(
        workspace_root=req.workspace_root,
        python_timeout_secs=req.python_timeout_secs,
        python_max_output_chars=req.python_max_output_chars,
        python_blocked_modules=req.python_blocked_modules,
        http_allowed_domains=req.http_allowed_domains,
        http_blocked_domains=req.http_blocked_domains,
        max_file_size_bytes=req.max_file_size_bytes,
    )
    new_cfg.to_yaml(state.sandbox_config_yaml)
    state.sandbox_manager._cfg = new_cfg
    return {"status": "ok"}
