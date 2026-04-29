from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING, AsyncIterator

from tts.tts.base import BaseTTSProvider

if TYPE_CHECKING:
    from config.tts.tts_config import TTSConfig

_CHUNK_SIZE = 4096


class KokoroProvider(BaseTTSProvider):
    def __init__(self, cfg: TTSConfig) -> None:
        self._model_path = cfg.kokoro_model_path
        self._device = cfg.kokoro_device
        self._voice = cfg.voice
        self._pipeline = None

    def _load(self):
        if self._pipeline is not None:
            return self._pipeline
        from kokoro import KPipeline  # type: ignore[import]

        self._pipeline = KPipeline(
            lang_code="z" if "zh" in self._voice.lower() else "a",
            model=self._model_path or None,
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
