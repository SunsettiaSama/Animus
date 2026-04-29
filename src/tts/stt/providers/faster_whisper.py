from __future__ import annotations

import asyncio
import os
import tempfile
from typing import TYPE_CHECKING

from tts.stt.base import BaseSTTProvider

if TYPE_CHECKING:
    from config.tts.stt_config import STTConfig


def _hf_download_whisper(
    repo_id: str,
    local_dir: str,
    endpoint: str = "",
    token: str = "",
) -> str:
    from huggingface_hub import snapshot_download

    kw: dict = {"local_dir": local_dir}
    if endpoint:
        kw["endpoint"] = endpoint
    if token:
        kw["token"] = token
    print(f"[faster-whisper] downloading {repo_id} → {local_dir}")
    path = snapshot_download(repo_id=repo_id, **kw)
    print(f"[faster-whisper] download complete → {path}")
    return path


class FasterWhisperProvider(BaseSTTProvider):
    def __init__(self, cfg: STTConfig) -> None:
        self._model_size = cfg.local_model_size
        self._model_path = cfg.local_model_path or None
        self._device = cfg.local_device if cfg.local_device != "auto" else "auto"
        self._compute_type = cfg.local_compute_type
        self._language = cfg.language or None
        self._hf_repo_id = cfg.local_hf_repo_id
        self._hf_endpoint = cfg.hf_endpoint
        self._hf_token = cfg.hf_token
        self._model = None

    def _resolve_model(self) -> str:
        # Explicit local path takes priority
        if self._model_path and os.path.isdir(self._model_path):
            return self._model_path

        # Determine the HF repo to download from
        repo_id = self._hf_repo_id or f"Systran/faster-whisper-{self._model_size}"

        if self._hf_endpoint or self._hf_token:
            # Explicit HF download into local models/ dir so it works offline after
            safe_name = repo_id.replace("/", "--")
            local_dir = os.path.join("models", "whisper", safe_name)
            if not os.path.isdir(local_dir):
                _hf_download_whisper(
                    repo_id=repo_id,
                    local_dir=local_dir,
                    endpoint=self._hf_endpoint,
                    token=self._hf_token,
                )
            return local_dir

        # No endpoint configured: let faster-whisper download to its own cache
        # (respects HF_ENDPOINT env var if set externally)
        return self._model_path or self._model_size

    def _load(self):
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel  # type: ignore[import]

        model_ref = self._resolve_model()
        self._model = WhisperModel(
            model_ref,
            device=self._device,
            compute_type=self._compute_type,
        )
        return self._model

    def _transcribe_sync(self, audio: bytes) -> str:
        model = self._load()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio)
            tmp_path = f.name
        segments, _ = model.transcribe(tmp_path, language=self._language)
        text = "".join(seg.text for seg in segments).strip()
        os.unlink(tmp_path)
        return text

    async def transcribe(self, audio: bytes, mime_type: str = "audio/webm") -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._transcribe_sync, audio)
