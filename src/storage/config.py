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
