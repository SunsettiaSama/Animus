from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ShortTermMemoryConfig:
    enabled: bool = True
    max_turns: int = 10
    max_tokens: int = 2048
    # 蒸馏：步骤溢出时自动压缩，保留推理精华
    distill_enabled: bool = True
    distill_trigger_steps: int = 4   # 积累 N 个驱逐步骤后触发一次 LLM 蒸馏
    max_distillate_tokens: int = 400  # 蒸馏结果的最大 token 数

    @classmethod
    def from_dict(cls, d: dict) -> ShortTermMemoryConfig:
        return cls(
            enabled=bool(d.get("enabled", True)),
            max_turns=int(d.get("max_turns", 10)),
            max_tokens=int(d.get("max_tokens", 2048)),
            distill_enabled=bool(d.get("distill_enabled", True)),
            distill_trigger_steps=int(d.get("distill_trigger_steps", 4)),
            max_distillate_tokens=int(d.get("max_distillate_tokens", 400)),
        )
