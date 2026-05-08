from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from state import get_state

router = APIRouter()


def _tts_status() -> dict:
    from config.tts.tts_config import TTSConfig
    from config import paths
    state = get_state()
    cfg = (
        TTSConfig.from_yaml(str(paths.tts_config_yaml))
        if paths.tts_config_yaml.exists()
        else TTSConfig()
    )
    return {
        "state":    "loaded" if state.tts_engine is not None else "unloaded",
        "provider": cfg.provider,
    }


def _stt_status() -> dict:
    from config.tts.stt_config import STTConfig
    from config import paths
    state = get_state()
    cfg = (
        STTConfig.from_yaml(str(paths.stt_config_yaml))
        if paths.stt_config_yaml.exists()
        else STTConfig()
    )
    return {
        "state":    "loaded" if state.stt_engine is not None else "unloaded",
        "provider": cfg.provider,
    }


@router.get("/api/services/status")
def services_status():
    state  = get_state()
    result = state.service_registry.status_all()
    result["tts"] = _tts_status()
    result["stt"] = _stt_status()
    return result


@router.get("/api/services/{name}/status")
def service_status(name: str):
    if name == "tts":
        return _tts_status()
    if name == "stt":
        return _stt_status()
    state = get_state()
    mgr   = state.service_registry.get(name)
    if mgr is None:
        return JSONResponse(status_code=404, content={"error": f"Unknown service: {name!r}"})
    return mgr.status()


@router.post("/api/services/{name}/start")
def service_start(name: str):
    import sys
    if name in ("vllm", "vllm-clone") and sys.platform == "win32":
        return JSONResponse(status_code=503, content={
            "error":          f"'{name}' is not available on Windows.",
            "recommendation": "Run this project inside WSL2 (ubuntu-24.04+).",
            "fallback":       "Use backend='transformers' in LLM config instead.",
        })

    state = get_state()
    mgr   = state.service_registry.get(name)
    if mgr is None:
        return JSONResponse(status_code=404, content={"error": f"Unknown service: {name!r}"})
    if name in ("vllm", "vllm-clone"):
        if state.llm_cfg is None or not state.llm_cfg.model:
            return JSONResponse(
                status_code=400,
                content={"error": "LLM not initialized. Set a model via /api/init first."},
            )
        from config.llm_core.vllm_config import VLLMConfig
        import os
        vllm_cfg = (
            VLLMConfig.from_yaml(state.vllm_config_yaml)
            if os.path.exists(state.vllm_config_yaml)
            else VLLMConfig()
        )
        mgr.start(state.llm_cfg.model, vllm_cfg)
    else:
        mgr.start()
    return {"status": "starting", "service": name}


@router.post("/api/services/{name}/stop")
def service_stop(name: str):
    state = get_state()
    mgr   = state.service_registry.get(name)
    if mgr is None:
        return JSONResponse(status_code=404, content={"error": f"Unknown service: {name!r}"})
    mgr.stop()
    return {"status": "stopped", "service": name}


@router.get("/api/services/{name}/logs")
def service_logs(name: str, n: int = 100):
    state = get_state()
    mgr   = state.service_registry.get(name)
    if mgr is None:
        return JSONResponse(status_code=404, content={"error": f"Unknown service: {name!r}"})
    return {"lines": mgr.get_logs(n), "service": name}
