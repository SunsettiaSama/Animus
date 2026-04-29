from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator

from tts.tts.base import BaseTTSProvider

if TYPE_CHECKING:
    from config.tts.tts_config import TTSConfig

_CHUNK_SIZE = 4096


class OpenAITTSProvider(BaseTTSProvider):
    def __init__(self, cfg: TTSConfig) -> None:
        self._model = cfg.openai_model
        self._voice = cfg.voice
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
    def _resolve_base_url() -> str | None:
        from config.llm_core.config import LLMConfig
        from config import paths

        if paths.llm_config_yaml.exists():
            return LLMConfig.from_yaml(str(paths.llm_config_yaml)).base_url
        return None

    def _client(self):
        import httpx

        base = self._base_url or self._resolve_base_url() or "https://api.openai.com"
        base = base.rstrip("/")
        return httpx.AsyncClient(
            base_url=base,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=60,
        )

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        async with self._client() as client:
            async with client.stream(
                "POST",
                "/v1/audio/speech",
                json={
                    "model": self._model,
                    "input": text,
                    "voice": self._voice,
                    "response_format": self._output_format,
                },
            ) as resp:
                resp.raise_for_status()
                async for chunk in resp.aiter_bytes(_CHUNK_SIZE):
                    yield chunk

    async def synthesize(self, text: str) -> bytes:
        async with self._client() as client:
            resp = await client.post(
                "/v1/audio/speech",
                json={
                    "model": self._model,
                    "input": text,
                    "voice": self._voice,
                    "response_format": self._output_format,
                },
            )
            resp.raise_for_status()
            return resp.content
