from __future__ import annotations

from typing import TYPE_CHECKING

from train.rl.base_rl_trainer import BaseRLTrainer

if TYPE_CHECKING:
    from config.train.rl_config import RLConfig
    from train.base_trainer import TrainResult
    from train.data.dataset import TrainDataset


class PPOTrainer(BaseRLTrainer):
    """PPO fine-tuning stub.

    Requires: trl.PPOTrainer, a reward model, and a reference model.
    Not yet implemented — reserved for future RL training support.
    """

    def __init__(self, rl_cfg: RLConfig) -> None:
        super().__init__()
        self._rl_cfg = rl_cfg

    def setup(self, model_name: str, **kwargs) -> None:
        raise NotImplementedError(
            "PPOTrainer is not yet implemented. "
            "Required: trl.PPOTrainer, reward model, reference model."
        )

    def train(self, dataset: TrainDataset) -> TrainResult:
        raise NotImplementedError("PPOTrainer is not yet implemented.")

    def save(self, output_dir: str) -> None:
        raise NotImplementedError("PPOTrainer is not yet implemented.")

    def rollout(self, prompts: list[str]) -> list[str]:
        raise NotImplementedError

    def compute_rewards(
        self, prompts: list[str], responses: list[str]
    ) -> list[float]:
        raise NotImplementedError

    def train_step(
        self, prompts: list[str], responses: list[str], rewards: list[float]
    ) -> dict:
        raise NotImplementedError
