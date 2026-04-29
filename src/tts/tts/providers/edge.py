from __future__ import annotations

import io
from typing import TYPE_CHECKING, AsyncIterator

from tts.tts.base import BaseTTSProvider

if TYPE_CHECKING:
    from config.tts.tts_config import TTSConfig


class EdgeTTSProvider(BaseTTSProvider):
    def __init__(self, cfg: TTSConfig) -> None:
        self._voice = cfg.voice
        self._rate = cfg.rate
        self._volume = cfg.volume

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        import edge_tts

        communicate = edge_tts.Communicate(
            text=text,
            voice=self._voice,
            rate=self._rate,
            volume=self._volume,
        )
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]

    async def synthesize(self, text: str) -> bytes:
        import edge_tts

        communicate = edge_tts.Communicate(
            text=text,
            voice=self._voice,
            rate=self._rate,
            volume=self._volume,
        )
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        return buf.getvalue()
