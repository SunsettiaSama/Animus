from __future__ import annotations

import asyncio
import io
import os
from typing import TYPE_CHECKING, AsyncIterator

from tts.tts.base import BaseTTSProvider

if TYPE_CHECKING:
    from config.tts.tts_config import TTSConfig

_CHUNK_SIZE = 4096


def _hf_download_kokoro(
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
    print(f"[kokoro] downloading {repo_id} → {local_dir}")
    path = snapshot_download(repo_id=repo_id, **kw)
    print(f"[kokoro] download complete → {path}")
    return path


class KokoroProvider(BaseTTSProvider):
    def __init__(self, cfg: TTSConfig) -> None:
        self._model_path = cfg.kokoro_model_path
        self._device = cfg.kokoro_device
        self._voice = cfg.voice
        self._hf_repo_id = cfg.kokoro_hf_repo_id
        self._hf_endpoint = cfg.hf_endpoint
        self._hf_token = cfg.hf_token
        self._pipeline = None

    def _resolve_model_path(self) -> str | None:
        if self._model_path:
            return self._model_path
        if self._hf_repo_id:
            # Derive a stable local cache dir from the repo id
            safe_name = self._hf_repo_id.replace("/", "--")
            local_dir = os.path.join("models", "kokoro", safe_name)
            if not os.path.isdir(local_dir):
                _hf_download_kokoro(
                    repo_id=self._hf_repo_id,
                    local_dir=local_dir,
                    endpoint=self._hf_endpoint,
                    token=self._hf_token,
                )
            return local_dir
        # Let KPipeline auto-download using its default HF logic
        if self._hf_endpoint:
            os.environ.setdefault("HF_ENDPOINT", self._hf_endpoint)
        if self._hf_token:
            os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", self._hf_token)
        return None

    def _load(self):
        if self._pipeline is not None:
            return self._pipeline
        from kokoro import KPipeline  # type: ignore[import]

        model_path = self._resolve_model_path()
        self._pipeline = KPipeline(
            lang_code="z" if "zh" in self._voice.lower() else "a",
            model=model_path,
            device=self._device if self._device != "auto" else None,
        )
        return self._pipeline

    def _synthesize_sync(self, text: str) -> bytes:
        import numpy as np
        import soundfile as sf

        pipeline = self._load()
        buf = io.BytesIO()
        for _, _, audio in pipeline(text, voice=self._voice):
            sf.write(buf, np.array(audio), 24000, format="WAV")
        return buf.getvalue()

    async def synthesize(self, text: str) -> bytes:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._synthesize_sync, text)

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        data = await self.synthesize(text)
        for i in range(0, len(data), _CHUNK_SIZE):
            yield data[i : i + _CHUNK_SIZE]
