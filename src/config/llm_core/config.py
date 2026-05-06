from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LLMConfig:
    model: str = ""
    api_key: str = ""
    base_url: str | None = None
    max_tokens: int = 512
    temperature: float = 1.0
    do_sample: bool = False
    top_p: float = 1.0
    top_k: int = 0
    repetition_penalty: float = 1.0
    device: str = "auto"
    system_prompt: str = ""
    backend: str = "openai"    # "openai" | "vllm" | "transformers"
    trained_model_path: str = ""

    @classmethod
    def from_yaml(cls, path: str) -> LLMConfig:
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls(
            model=data.get("model", ""),
            api_key=data.get("api_key", ""),
            base_url=data.get("base_url") or None,
            max_tokens=int(data.get("max_tokens", 512)),
            temperature=float(data.get("temperature", 1.0)),
            do_sample=bool(data.get("do_sample", False)),
            top_p=float(data.get("top_p", 1.0)),
            top_k=int(data.get("top_k", 0)),
            repetition_penalty=float(data.get("repetition_penalty", 1.0)),
            device=data.get("device", "auto"),
            system_prompt=data.get("system_prompt", ""),
            backend=data.get("backend", "openai"),
            trained_model_path=data.get("trained_model_path", ""),
        )

    def to_dict(self) -> dict:
        return {
            "model":              self.model,
            "api_key":            self.api_key,
            "base_url":           self.base_url or "",
            "max_tokens":         self.max_tokens,
            "temperature":        self.temperature,
            "do_sample":          self.do_sample,
            "top_p":              self.top_p,
            "top_k":              self.top_k,
            "repetition_penalty": self.repetition_penalty,
            "device":             self.device,
            "system_prompt":      self.system_prompt,
            "backend":             self.backend,
            "trained_model_path":  self.trained_model_path,
        }

    def save_yaml(self, path: str) -> None:
        import os
        import yaml

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, allow_unicode=True, default_flow_style=False)
