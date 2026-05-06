from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class QuantConfig:
    load_in_4bit: bool = True
    load_in_8bit: bool = False
    bnb_4bit_compute_dtype: str = "bfloat16"
    bnb_4bit_use_double_quant: bool = True
    bnb_4bit_quant_type: str = "nf4"
    skip_modules: list[str] = field(
        default_factory=lambda: ["embed_tokens", "lm_head"]
    )

    @classmethod
    def from_yaml(cls, path: str) -> QuantConfig:
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls(
            load_in_4bit=bool(data.get("load_in_4bit", True)),
            load_in_8bit=bool(data.get("load_in_8bit", False)),
            bnb_4bit_compute_dtype=data.get("bnb_4bit_compute_dtype", "bfloat16"),
            bnb_4bit_use_double_quant=bool(data.get("bnb_4bit_use_double_quant", True)),
            bnb_4bit_quant_type=data.get("bnb_4bit_quant_type", "nf4"),
            skip_modules=list(data.get("skip_modules", ["embed_tokens", "lm_head"])),
        )

    def to_dict(self) -> dict:
        return {
            "load_in_4bit":              self.load_in_4bit,
            "load_in_8bit":              self.load_in_8bit,
            "bnb_4bit_compute_dtype":    self.bnb_4bit_compute_dtype,
            "bnb_4bit_use_double_quant": self.bnb_4bit_use_double_quant,
            "bnb_4bit_quant_type":       self.bnb_4bit_quant_type,
            "skip_modules":              self.skip_modules,
        }

    def save_yaml(self, path: str) -> None:
        import yaml

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, allow_unicode=True, default_flow_style=False)

    def to_bnb_config(self):
        import importlib.util

        if importlib.util.find_spec("bitsandbytes") is None:
            raise RuntimeError(
                "QuantConfig requires the bitsandbytes package.\n"
                "Install with: pip install bitsandbytes"
            )
        import torch
        from transformers import BitsAndBytesConfig

        _dtype_map = {
            "bfloat16": torch.bfloat16,
            "float16":  torch.float16,
            "float32":  torch.float32,
        }
        compute_dtype = _dtype_map.get(self.bnb_4bit_compute_dtype, torch.bfloat16)

        return BitsAndBytesConfig(
            load_in_4bit=self.load_in_4bit,
            load_in_8bit=self.load_in_8bit,
            bnb_4bit_compute_dtype=compute_dtype,
            bnb_4bit_use_double_quant=self.bnb_4bit_use_double_quant,
            bnb_4bit_quant_type=self.bnb_4bit_quant_type,
            llm_int8_skip_modules=self.skip_modules if self.load_in_8bit else None,
        )
