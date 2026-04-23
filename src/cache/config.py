from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class CacheConfig:
    """
    Agent 缓存根目录配置。

    所有运行时产出的持久化文件都位于 `root` 下的固定子目录。
    `root` 可以是相对路径（相对于进程 CWD）或绝对路径。

    默认目录结构：
        <root>/
        ├── history/   — 对话历史 JSON（仅 WebUI 写入）
        ├── memory/    — 长期记忆（memories.json + FAISS 索引）
        ├── persona/   — 人格数据（profile / chronicle / skills / reflection）
        └── traces/    — 推理链存档 JSON
    """

    root: str = ".react"

    @classmethod
    def from_dict(cls, data: dict) -> CacheConfig:
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
