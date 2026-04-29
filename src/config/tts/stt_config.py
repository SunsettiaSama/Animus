from __future__ import annotations

from dataclasses import dataclass


@dataclass
class STTConfig:
    provider: str = "openai"
    language: str = "zh"
    output_format: str = "text"

    openai_model: str = "whisper-1"
    openai_base_url: str = ""
    openai_api_key: str = ""

    local_model_size: str = "base"
    local_model_path: str = ""
    local_device: str = "auto"
    local_compute_type: str = "int8"

    @classmethod
    def from_yaml(cls, path: str) -> STTConfig:
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, d: dict) -> STTConfig:
        return cls(
            provider=d.get("provider", "openai"),
            language=d.get("language", "zh"),
            output_format=d.get("output_format", "text"),
            openai_model=d.get("openai_model", "whisper-1"),
            openai_base_url=d.get("openai_base_url", ""),
            openai_api_key=d.get("openai_api_key", ""),
            local_model_size=d.get("local_model_size", "base"),
            local_model_path=d.get("local_model_path", ""),
            local_device=d.get("local_device", "auto"),
            local_compute_type=d.get("local_compute_type", "int8"),
        )
