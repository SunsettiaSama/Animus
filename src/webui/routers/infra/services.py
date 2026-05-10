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
    state = get_state()

    if name == "llm":
        if state.llm_cfg is None or not state.llm_cfg.model:
            return JSONResponse(
                status_code=400,
                content={"error": "Configure a model in Settings → LLM Core first."},
            )
        try:
            import os
            from config.llm_core.vllm_config import VLLMConfig
            vllm_cfg = (
                VLLMConfig.from_yaml(state.vllm_config_yaml)
                if os.path.exists(state.vllm_config_yaml)
                else VLLMConfig()
            )
            state.llm_service.start(state.llm_cfg, vllm_cfg)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
        return {"status": "starting", "service": "llm"}

    mgr = state.service_registry.get(name)
    if mgr is None:
        return JSONResponse(status_code=404, content={"error": f"Unknown service: {name!r}"})

    # Run the potentially slow Docker operation (image pull + container start)
    # in the background so the HTTP response returns immediately.
    state.task_runner.submit(f"start_{name}", mgr.start)
    return {"status": "starting", "service": name}


@router.post("/api/services/{name}/stop")
def service_stop(name: str):
    state = get_state()
    mgr   = state.service_registry.get(name)
    if name == "llm":
        try:
            state.llm_service.stop()
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
        return {"status": "stopped", "service": "llm"}
    if mgr is None:
        return JSONResponse(status_code=404, content={"error": f"Unknown service: {name!r}"})
    try:
        mgr.stop()
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    return {"status": "stopped", "service": name}


@router.get("/api/services/{name}/logs")
def service_logs(name: str, n: int = 100):
    state = get_state()
    mgr   = state.service_registry.get(name)
    if mgr is None:
        return JSONResponse(status_code=404, content={"error": f"Unknown service: {name!r}"})
    return {"lines": mgr.get_logs(n), "service": name}
