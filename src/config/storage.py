from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class StorageConfig:
    root: str = ".react"

    @classmethod
    def from_dict(cls, data: dict) -> StorageConfig:
        return cls(root=data.get("root", ".react"))

    @property
    def history_dir(self) -> str:
        return os.path.join(self.root, "history")

    @property
    def memory_dir(self) -> str:
        return os.path.join(self.root, "memory")

    @property
    def persona_dir(self) -> str:
        return os.path.join(self.root, "persona")

    @property
    def milestones_dir(self) -> str:
        return os.path.join(self.root, "milestones")

    @property
    def traces_dir(self) -> str:
        return os.path.join(self.root, "traces")

    @property
    def scheduler_dir(self) -> str:
        return os.path.join(self.root, "scheduler")

    @property
    def workspace_dir(self) -> str:
        return os.path.join(self.root, "workspace")

    @property
    def timeline_dir(self) -> str:
        return os.path.join(self.root, "timeline")

    @property
    def life_dir(self) -> str:
        return os.path.join(self.root, "life")

    @property
    def benchmark_dir(self) -> str:
        return os.path.join(self.root, "benchmark")

    @property
    def obs_dir(self) -> str:
        return os.path.join(self.root, "logs")

    @property
    def train_dir(self) -> str:
        return os.path.join(self.root, "train")

    @property
    def checkpoints_dir(self) -> str:
        return os.path.join(self.root, "train", "checkpoints")

    @property
    def adapters_dir(self) -> str:
        return os.path.join(self.root, "train", "adapters")

    @property
    def merged_dir(self) -> str:
        return os.path.join(self.root, "train", "merged")
