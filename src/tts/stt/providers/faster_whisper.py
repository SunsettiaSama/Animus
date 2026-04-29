from __future__ import annotations

import asyncio
import io
import tempfile
import os
from typing import TYPE_CHECKING

from tts.stt.base import BaseSTTProvider

if TYPE_CHECKING:
    from config.tts.stt_config import STTConfig


class FasterWhisperProvider(BaseSTTProvider):
    def __init__(self, cfg: STTConfig) -> None:
        self._model_size = cfg.local_model_size
        self._model_path = cfg.local_model_path or None
        self._device = cfg.local_device if cfg.local_device != "auto" else "auto"
        self._compute_type = cfg.local_compute_type
        self._language = cfg.language or None
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel  # type: ignore[import]

        self._model = WhisperModel(
            self._model_path or self._model_size,
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
