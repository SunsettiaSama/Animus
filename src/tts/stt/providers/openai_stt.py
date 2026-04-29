from __future__ import annotations

from typing import TYPE_CHECKING

from tts.stt.base import BaseSTTProvider

if TYPE_CHECKING:
    from config.tts.stt_config import STTConfig

_MIME_TO_EXT = {
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/flac": "flac",
}


class OpenAISTTProvider(BaseSTTProvider):
    def __init__(self, cfg: STTConfig) -> None:
        self._model = cfg.openai_model
        self._language = cfg.language
        self._output_format = cfg.output_format
        self._base_url = cfg.openai_base_url or None
        self._api_key = cfg.openai_api_key or self._resolve_api_key()

    @staticmethod
    def _resolve_api_key() -> str:
        from config.llm_core.config import LLMConfig
        from config import paths

        if paths.llm_config_yaml.exists():
            return LLMConfig.from_yaml(str(paths.llm_config_yaml)).api_key
        return ""

    @staticmethod
    def _resolve_base_url() -> str:
        from config.llm_core.config import LLMConfig
        from config import paths

        if paths.llm_config_yaml.exists():
            url = LLMConfig.from_yaml(str(paths.llm_config_yaml)).base_url
            return url or "https://api.openai.com"
        return "https://api.openai.com"

    def _base(self) -> str:
        return (self._base_url or self._resolve_base_url()).rstrip("/")

    async def transcribe(self, audio: bytes, mime_type: str = "audio/webm") -> str:
        import httpx

        ext = _MIME_TO_EXT.get(mime_type, "webm")
        filename = f"audio.{ext}"

        async with httpx.AsyncClient(
            base_url=self._base(),
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=120,
        ) as client:
            resp = await client.post(
                "/v1/audio/transcriptions",
                files={"file": (filename, audio, mime_type)},
                data={
                    "model": self._model,
                    "language": self._language,
                    "response_format": self._output_format,
                },
            )
            resp.raise_for_status()
            if self._output_format == "text":
                return resp.text.strip()
            return resp.json().get("text", "").strip()
