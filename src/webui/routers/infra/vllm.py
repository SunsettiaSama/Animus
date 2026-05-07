from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from state import get_state

router = APIRouter()


class VLLMConfigSaveRequest(BaseModel):
    provider: str = "official"
    host: str = "127.0.0.1"
    port: int = 8000
    tensor_parallel_size: int = 1
    pipeline_parallel_size: int = 1
    gpu_memory_utilization: float = 0.90
    max_model_len: int | None = None
    quantization: str | None = None
    dtype: str = "auto"
    enable_lora: bool = False
    max_lora_rank: int = 16
    enforce_eager: bool = False


def _load_vllm_config():
    from config.llm_core.vllm_config import VLLMConfig
    state = get_state()
    import os
    if os.path.exists(state.vllm_config_yaml):
        return VLLMConfig.from_yaml(state.vllm_config_yaml)
    return VLLMConfig()


@router.get("/api/vllm/config")
def get_vllm_config():
    return _load_vllm_config().to_dict()


@router.post("/api/vllm/config/save")
def save_vllm_config(req: VLLMConfigSaveRequest):
    from config.llm_core.vllm_config import VLLMConfig
    state = get_state()
    cfg = VLLMConfig(
        provider=req.provider,
        host=req.host,
        port=req.port,
        tensor_parallel_size=req.tensor_parallel_size,
        pipeline_parallel_size=req.pipeline_parallel_size,
        gpu_memory_utilization=req.gpu_memory_utilization,
        max_model_len=req.max_model_len,
        quantization=req.quantization or None,
        dtype=req.dtype,
        enable_lora=req.enable_lora,
        max_lora_rank=req.max_lora_rank,
        enforce_eager=req.enforce_eager,
    )
    cfg.save_yaml(state.vllm_config_yaml)
    return {"status": "ok"}


@router.post("/api/vllm/start")
def vllm_start():
    state = get_state()
    if state.llm_cfg is None or not state.llm_cfg.model:
        return JSONResponse(
            status_code=400,
            content={"error": "LLM not initialized. Set a model via /api/init first."},
        )
    cfg = _load_vllm_config()
    state.vllm_manager.start(state.llm_cfg.model, cfg)
    return {"status": "starting", "model": state.llm_cfg.model}


@router.post("/api/vllm/stop")
def vllm_stop():
    get_state().vllm_manager.stop()
    return {"status": "stopped"}


@router.get("/api/vllm/status")
def vllm_status():
    state = get_state()
    s = state.vllm_manager.status()
    cfg = _load_vllm_config()
    s.setdefault("provider", cfg.provider)
    return s


@router.get("/api/vllm/logs")
def vllm_logs(n: int = 100):
    return {"lines": get_state().vllm_manager.get_logs(n)}
