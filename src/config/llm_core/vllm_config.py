from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class VLLMConfig:
    provider: str = "official"     # "official" | "custom"
    host: str = "127.0.0.1"
    port: int = 8000
    tensor_parallel_size: int = 1
    pipeline_parallel_size: int = 1
    gpu_memory_utilization: float = 0.90
    max_model_len: Optional[int] = None
    quantization: Optional[str] = None     # "awq" | "gptq" | "fp8" | None
    dtype: str = "auto"                    # "auto" | "float16" | "bfloat16"
    enable_lora: bool = False
    max_lora_rank: int = 16
    enforce_eager: bool = False

    @classmethod
    def from_yaml(cls, path: str) -> VLLMConfig:
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls(
            provider=data.get("provider", "official"),
            host=data.get("host", "127.0.0.1"),
            port=int(data.get("port", 8000)),
            tensor_parallel_size=int(data.get("tensor_parallel_size", 1)),
            pipeline_parallel_size=int(data.get("pipeline_parallel_size", 1)),
            gpu_memory_utilization=float(data.get("gpu_memory_utilization", 0.90)),
            max_model_len=data.get("max_model_len") or None,
            quantization=data.get("quantization") or None,
            dtype=data.get("dtype", "auto"),
            enable_lora=bool(data.get("enable_lora", False)),
            max_lora_rank=int(data.get("max_lora_rank", 16)),
            enforce_eager=bool(data.get("enforce_eager", False)),
        )

    def to_dict(self) -> dict:
        return {
            "provider":               self.provider,
            "host":                   self.host,
            "port":                   self.port,
            "tensor_parallel_size":   self.tensor_parallel_size,
            "pipeline_parallel_size": self.pipeline_parallel_size,
            "gpu_memory_utilization": self.gpu_memory_utilization,
            "max_model_len":          self.max_model_len,
            "quantization":           self.quantization,
            "dtype":                  self.dtype,
            "enable_lora":            self.enable_lora,
            "max_lora_rank":          self.max_lora_rank,
            "enforce_eager":          self.enforce_eager,
        }

    def save_yaml(self, path: str) -> None:
        import os
        import yaml

        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, allow_unicode=True, default_flow_style=False)

    def to_cli_args(self, model: str) -> list[str]:
        args = [
            "vllm", "serve", model,
            "--host", self.host,
            "--port", str(self.port),
            "--tensor-parallel-size", str(self.tensor_parallel_size),
            "--pipeline-parallel-size", str(self.pipeline_parallel_size),
            "--gpu-memory-utilization", str(self.gpu_memory_utilization),
            "--dtype", self.dtype,
        ]
        if self.max_model_len is not None:
            args += ["--max-model-len", str(self.max_model_len)]
        if self.quantization:
            args += ["--quantization", self.quantization]
        if self.enable_lora:
            args += ["--enable-lora", "--max-lora-rank", str(self.max_lora_rank)]
        if self.enforce_eager:
            args.append("--enforce-eager")
        return args
