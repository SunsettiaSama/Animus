from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class LoRAConfig:
    r: int = 8
    lora_alpha: int = 16
    lora_dropout: float = 0.05
    target_modules: list[str] = field(default_factory=lambda: ["q_proj", "v_proj"])
    bias: str = "none"
    task_type: str = "CAUSAL_LM"

    @classmethod
    def from_yaml(cls, path: str) -> LoRAConfig:
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls(
            r=int(data.get("r", 8)),
            lora_alpha=int(data.get("lora_alpha", 16)),
            lora_dropout=float(data.get("lora_dropout", 0.05)),
            target_modules=list(data.get("target_modules", ["q_proj", "v_proj"])),
            bias=data.get("bias", "none"),
            task_type=data.get("task_type", "CAUSAL_LM"),
        )

    def to_dict(self) -> dict:
        return {
            "r": self.r,
            "lora_alpha": self.lora_alpha,
            "lora_dropout": self.lora_dropout,
            "target_modules": self.target_modules,
            "bias": self.bias,
            "task_type": self.task_type,
        }

    def save_yaml(self, path: str) -> None:
        import yaml

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, allow_unicode=True, default_flow_style=False)

    def to_peft_config(self):
        from peft import LoraConfig, TaskType

        return LoraConfig(
            r=self.r,
            lora_alpha=self.lora_alpha,
            lora_dropout=self.lora_dropout,
            target_modules=self.target_modules,
            bias=self.bias,
            task_type=TaskType.CAUSAL_LM,
        )
