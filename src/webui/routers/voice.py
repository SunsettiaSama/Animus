from __future__ import annotations

import json
import os

from fastapi import APIRouter, File, UploadFile, WebSocket
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from state import get_state

router = APIRouter()


# ── Request models ────────────────────────────────────────────────────────────

class TTSSynthesizeRequest(BaseModel):
    text: str


class TTSConfigSaveRequest(BaseModel):
    provider: str = "edge"
    voice: str = "zh-CN-XiaoxiaoNeural"
    rate: str = "+0%"
    volume: str = "+0%"
    output_format: str = "mp3"
    openai_model: str = "tts-1"
    openai_base_url: str = ""
    openai_api_key: str = ""
    kokoro_model_path: str = ""
    kokoro_device: str = "auto"
    kokoro_hf_repo_id: str = "hexgrad/Kokoro-82M"
    hf_endpoint: str = ""
    hf_token: str = ""


class STTConfigSaveRequest(BaseModel):
    provider: str = "openai"
    language: str = "zh"
    openai_model: str = "whisper-1"
    openai_base_url: str = ""
    openai_api_key: str = ""
    local_model_size: str = "base"
    local_model_path: str = ""
    local_device: str = "auto"
    local_compute_type: str = "int8"
    local_hf_repo_id: str = ""
    hf_endpoint: str = ""
    hf_token: str = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_tts():
    state = get_state()
    if state.tts_engine is None:
        from tts import TTSEngine
        from config.tts.tts_config import TTSConfig
        from config import paths
        cfg = (
            TTSConfig.from_yaml(str(paths.tts_config_yaml))
            if paths.tts_config_yaml.exists()
            else TTSConfig()
        )
        state.tts_engine = TTSEngine.from_config(cfg)
    return state.tts_engine


def _get_stt():
    state = get_state()
    if state.stt_engine is None:
        from tts import STTEngine
        from config.tts.stt_config import STTConfig
        from config import paths
        cfg = (
            STTConfig.from_yaml(str(paths.stt_config_yaml))
            if paths.stt_config_yaml.exists()
            else STTConfig()
        )
        state.stt_engine = STTEngine.from_config(cfg)
    return state.stt_engine


# ── TTS config ────────────────────────────────────────────────────────────────

@router.get("/api/tts/config")
def get_tts_config():
    from config.tts.tts_config import TTSConfig
    from config import paths
    cfg = (
        TTSConfig.from_yaml(str(paths.tts_config_yaml))
        if paths.tts_config_yaml.exists()
        else TTSConfig()
    )
    return {
        "provider":          cfg.provider,
        "voice":             cfg.voice,
        "rate":              cfg.rate,
        "volume":            cfg.volume,
        "output_format":     cfg.output_format,
        "openai_model":      cfg.openai_model,
        "openai_base_url":   cfg.openai_base_url,
        "openai_api_key":    cfg.openai_api_key,
        "kokoro_model_path": cfg.kokoro_model_path,
        "kokoro_device":     cfg.kokoro_device,
        "kokoro_hf_repo_id": cfg.kokoro_hf_repo_id,
        "hf_endpoint":       cfg.hf_endpoint,
        "hf_token":          cfg.hf_token,
    }


@router.post("/api/tts/config/save")
def save_tts_config(req: TTSConfigSaveRequest):
    import yaml
    from config import paths
    os.makedirs(paths.tts_config_yaml.parent, exist_ok=True)
    data = {
        "provider":          req.provider,
        "voice":             req.voice,
        "rate":              req.rate,
        "volume":            req.volume,
        "output_format":     req.output_format,
        "openai_model":      req.openai_model,
        "openai_base_url":   req.openai_base_url,
        "openai_api_key":    req.openai_api_key,
        "kokoro_model_path": req.kokoro_model_path,
        "kokoro_device":     req.kokoro_device,
        "kokoro_hf_repo_id": req.kokoro_hf_repo_id,
        "hf_endpoint":       req.hf_endpoint,
        "hf_token":          req.hf_token,
    }
    with open(paths.tts_config_yaml, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    state = get_state()
    state.tts_engine = None   # force re-init on next use
    return {"status": "ok"}


# ── STT config ────────────────────────────────────────────────────────────────

@router.get("/api/stt/config")
def get_stt_config():
    from config.tts.stt_config import STTConfig
    from config import paths
    cfg = (
        STTConfig.from_yaml(str(paths.stt_config_yaml))
        if paths.stt_config_yaml.exists()
        else STTConfig()
    )
    return {
        "provider":           cfg.provider,
        "language":           cfg.language,
        "openai_model":       cfg.openai_model,
        "openai_base_url":    cfg.openai_base_url,
        "openai_api_key":     cfg.openai_api_key,
        "local_model_size":   cfg.local_model_size,
        "local_model_path":   cfg.local_model_path,
        "local_device":       cfg.local_device,
        "local_compute_type": cfg.local_compute_type,
        "local_hf_repo_id":   cfg.local_hf_repo_id,
        "hf_endpoint":        cfg.hf_endpoint,
        "hf_token":           cfg.hf_token,
    }


@router.post("/api/stt/config/save")
def save_stt_config(req: STTConfigSaveRequest):
    import yaml
    from config import paths
    os.makedirs(paths.stt_config_yaml.parent, exist_ok=True)
    data = {
        "provider":           req.provider,
        "language":           req.language,
        "openai_model":       req.openai_model,
        "openai_base_url":    req.openai_base_url,
        "openai_api_key":     req.openai_api_key,
        "local_model_size":   req.local_model_size,
        "local_model_path":   req.local_model_path,
        "local_device":       req.local_device,
        "local_compute_type": req.local_compute_type,
        "local_hf_repo_id":   req.local_hf_repo_id,
        "hf_endpoint":        req.hf_endpoint,
        "hf_token":           req.hf_token,
    }
    with open(paths.stt_config_yaml, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    state = get_state()
    state.stt_engine = None   # force re-init on next use
    return {"status": "ok"}


# ── TTS synthesize ────────────────────────────────────────────────────────────

@router.post("/api/tts/synthesize")
async def tts_synthesize(req: TTSSynthesizeRequest):
    engine = _get_tts()
    audio  = await engine.synthesize(req.text)
    return Response(content=audio, media_type="audio/mpeg")


@router.websocket("/ws/tts")
async def ws_tts(websocket: WebSocket):
    await websocket.accept()
    data = await websocket.receive_json()
    text = data.get("text", "")
    if not text:
        await websocket.send_json({"error": "No text provided."})
        await websocket.close()
        return
    engine = _get_tts()
    async for chunk in engine.stream(text):
        await websocket.send_bytes(chunk)
    await websocket.close()


# ── STT transcribe ────────────────────────────────────────────────────────────

@router.post("/api/stt/transcribe")
async def stt_transcribe(audio: UploadFile = File(...)):
    engine = _get_stt()
    data   = await audio.read()
    mime   = audio.content_type or "audio/webm"
    text   = await engine.transcribe(data, mime)
    return {"text": text}


@router.websocket("/ws/stt")
async def ws_stt(websocket: WebSocket):
    await websocket.accept()
    chunks: list[bytes] = []
    mime_type = "audio/webm"
    while True:
        msg = await websocket.receive()
        if "bytes" in msg:
            chunks.append(msg["bytes"])
        elif "text" in msg:
            payload = json.loads(msg["text"])
            if payload.get("done"):
                mime_type = payload.get("mime_type", mime_type)
                break
    audio  = b"".join(chunks)
    engine = _get_stt()
    text   = await engine.transcribe(audio, mime_type)
    await websocket.send_json({"text": text})
    await websocket.close()


# ── Model download (SSE) ──────────────────────────────────────────────────────

@router.get("/api/tts/download")
def tts_download():
    import queue, threading
    from config.tts.tts_config import TTSConfig
    from config import paths
    cfg      = (
        TTSConfig.from_yaml(str(paths.tts_config_yaml))
        if paths.tts_config_yaml.exists()
        else TTSConfig()
    )
    repo_id   = cfg.kokoro_hf_repo_id or "hexgrad/Kokoro-82M"
    safe      = repo_id.replace("/", "--")
    local_dir = os.path.join("models", "kokoro", safe)

    def generate():
        q: queue.Queue = queue.Queue()

        def _dl():
            from huggingface_hub import snapshot_download
            kw: dict = {"local_dir": local_dir}
            if cfg.hf_endpoint:
                kw["endpoint"] = cfg.hf_endpoint
            if cfg.hf_token:
                kw["token"] = cfg.hf_token
            q.put(json.dumps({"status": "start", "repo": repo_id, "local_dir": local_dir}))
            path = snapshot_download(repo_id=repo_id, **kw)
            q.put(json.dumps({"status": "done", "path": path}))

        threading.Thread(target=_dl, daemon=True).start()
        while True:
            msg = q.get()
            yield f"data: {msg}\n\n"
            if json.loads(msg).get("status") in ("done", "error"):
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/api/stt/download")
def stt_download():
    import queue, threading
    from config.tts.stt_config import STTConfig
    from config import paths
    cfg      = (
        STTConfig.from_yaml(str(paths.stt_config_yaml))
        if paths.stt_config_yaml.exists()
        else STTConfig()
    )
    repo_id   = cfg.local_hf_repo_id or f"Systran/faster-whisper-{cfg.local_model_size}"
    safe      = repo_id.replace("/", "--")
    local_dir = os.path.join("models", "whisper", safe)

    def generate():
        q: queue.Queue = queue.Queue()

        def _dl():
            from huggingface_hub import snapshot_download
            kw: dict = {"local_dir": local_dir}
            if cfg.hf_endpoint:
                kw["endpoint"] = cfg.hf_endpoint
            if cfg.hf_token:
                kw["token"] = cfg.hf_token
            q.put(json.dumps({"status": "start", "repo": repo_id, "local_dir": local_dir}))
            path = snapshot_download(repo_id=repo_id, **kw)
            q.put(json.dumps({"status": "done", "path": path}))

        threading.Thread(target=_dl, daemon=True).start()
        while True:
            msg = q.get()
            yield f"data: {msg}\n\n"
            if json.loads(msg).get("status") in ("done", "error"):
                break

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
