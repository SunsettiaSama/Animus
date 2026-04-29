from __future__ import annotations

from typing import TYPE_CHECKING

from tts.stt.base import BaseSTTProvider

if TYPE_CHECKING:
    from config.tts.stt_config import STTConfig


class STTEngine:
    def __init__(self, provider: BaseSTTProvider) -> None:
        self._provider = provider

    @classmethod
    def from_config(cls, cfg: STTConfig) -> STTEngine:
        if cfg.provider == "openai":
            from tts.stt.providers.openai_stt import OpenAISTTProvider
            return cls(OpenAISTTProvider(cfg))
        if cfg.provider == "faster_whisper":
            from tts.stt.providers.faster_whisper import FasterWhisperProvider
            return cls(FasterWhisperProvider(cfg))
        raise ValueError(f"Unknown STT provider: {cfg.provider!r}")

    @classmethod
    def from_yaml(cls, path: str) -> STTEngine:
        from config.tts.stt_config import STTConfig
        return cls.from_config(STTConfig.from_yaml(path))

    async def transcribe(self, audio: bytes, mime_type: str = "audio/webm") -> str:
        return await self._provider.transcribe(audio, mime_type)
