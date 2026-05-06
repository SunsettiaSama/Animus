from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class RLConfig:
    algorithm: str = "ppo"
    kl_coef: float = 0.1
    clip_range: float = 0.2
    vf_coef: float = 0.5
    reward_model: str = ""
    max_new_tokens: int = 256
    mini_batch_size: int = 1
    ppo_epochs: int = 4

    @classmethod
    def from_yaml(cls, path: str) -> RLConfig:
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls(
            algorithm=data.get("algorithm", "ppo"),
            kl_coef=float(data.get("kl_coef", 0.1)),
            clip_range=float(data.get("clip_range", 0.2)),
            vf_coef=float(data.get("vf_coef", 0.5)),
            reward_model=data.get("reward_model", ""),
            max_new_tokens=int(data.get("max_new_tokens", 256)),
            mini_batch_size=int(data.get("mini_batch_size", 1)),
            ppo_epochs=int(data.get("ppo_epochs", 4)),
        )

    def to_dict(self) -> dict:
        return {
            "algorithm":       self.algorithm,
            "kl_coef":         self.kl_coef,
            "clip_range":      self.clip_range,
            "vf_coef":         self.vf_coef,
            "reward_model":    self.reward_model,
            "max_new_tokens":  self.max_new_tokens,
            "mini_batch_size": self.mini_batch_size,
            "ppo_epochs":      self.ppo_epochs,
        }

    def save_yaml(self, path: str) -> None:
        import yaml

        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(self.to_dict(), f, allow_unicode=True, default_flow_style=False)
