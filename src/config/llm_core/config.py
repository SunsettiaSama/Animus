from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LLMConfig:
    model: str
    api_key: str = ""
    base_url: str | None = None
    max_tokens: int = 512
    temperature: float = 1.0
    do_sample: bool = False
    device: str = "auto"
    system_prompt: str = ""
