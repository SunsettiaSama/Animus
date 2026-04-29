from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TTSConfig:
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

    @classmethod
    def from_yaml(cls, path: str) -> TTSConfig:
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, d: dict) -> TTSConfig:
        return cls(
            provider=d.get("provider", "edge"),
            voice=d.get("voice", "zh-CN-XiaoxiaoNeural"),
            rate=d.get("rate", "+0%"),
            volume=d.get("volume", "+0%"),
            output_format=d.get("output_format", "mp3"),
            openai_model=d.get("openai_model", "tts-1"),
            openai_base_url=d.get("openai_base_url", ""),
            openai_api_key=d.get("openai_api_key", ""),
            kokoro_model_path=d.get("kokoro_model_path", ""),
            kokoro_device=d.get("kokoro_device", "auto"),
        )
