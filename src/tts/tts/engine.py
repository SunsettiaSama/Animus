from __future__ import annotations

from typing import AsyncIterator, TYPE_CHECKING

from tts.tts.base import BaseTTSProvider

if TYPE_CHECKING:
    from config.tts.tts_config import TTSConfig


class TTSEngine:
    def __init__(self, provider: BaseTTSProvider) -> None:
        self._provider = provider

    @classmethod
    def from_config(cls, cfg: TTSConfig) -> TTSEngine:
        if cfg.provider == "edge":
            from tts.tts.providers.edge import EdgeTTSProvider
            return cls(EdgeTTSProvider(cfg))
        if cfg.provider == "openai":
            from tts.tts.providers.openai_tts import OpenAITTSProvider
            return cls(OpenAITTSProvider(cfg))
        if cfg.provider == "kokoro":
            from tts.tts.providers.kokoro import KokoroProvider
            return cls(KokoroProvider(cfg))
        raise ValueError(f"Unknown TTS provider: {cfg.provider!r}")

    @classmethod
    def from_yaml(cls, path: str) -> TTSEngine:
        from config.tts.tts_config import TTSConfig
        return cls.from_config(TTSConfig.from_yaml(path))

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        async for chunk in self._provider.stream(text):
            yield chunk

    async def synthesize(self, text: str) -> bytes:
        return await self._provider.synthesize(text)
