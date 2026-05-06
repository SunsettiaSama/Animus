from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from train.base_trainer import BaseTrainer

if TYPE_CHECKING:
    from train.base_trainer import TrainResult
    from train.data.dataset import TrainDataset


class BaseRLTrainer(BaseTrainer):
    """Abstract base for reinforcement-learning-based fine-tuning.

    Concrete implementations (PPO, GRPO, DPO, …) extend this class and
    provide the reward signal, rollout generation, and per-step update.
    The inherited ``train()`` orchestrates the outer loop; subclasses fill
    in the three abstract methods below.
    """

    @abstractmethod
    def rollout(self, prompts: list[str]) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def compute_rewards(
        self, prompts: list[str], responses: list[str]
    ) -> list[float]:
        raise NotImplementedError

    @abstractmethod
    def train_step(
        self, prompts: list[str], responses: list[str], rewards: list[float]
    ) -> dict:
        raise NotImplementedError
