from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MediumTermMemoryConfig:
    enabled: bool = True
    window_days: int = 7       # 加载最近 N 天的条目
    max_entries: int = 30      # 最多加载 N 条（取最新）
    max_chars: int = 3000      # 注入 prompt 的字符上限（截取最新部分）
    memory_dir: str = ""       # 由 TaoConfig._propagate_dirs 自动填充
    # 滚动整合：把最旧的一批条目蒸馏为单条摘要
    consolidate_enabled: bool = True
    consolidate_batch: int = 10        # 每次整合的旧条目数
    consolidate_interval_days: int = 1 # 自动整合的最短间隔（天）；0 = 每次提交都检查
    max_consolidate_tokens: int = 500  # 摘要 token 上限

    @classmethod
    def from_dict(cls, d: dict) -> MediumTermMemoryConfig:
        return cls(
            enabled=bool(d.get("enabled", True)),
            window_days=int(d.get("window_days", 7)),
            max_entries=int(d.get("max_entries", 30)),
            max_chars=int(d.get("max_chars", 3000)),
            memory_dir=d.get("memory_dir", ""),
            consolidate_enabled=bool(d.get("consolidate_enabled", True)),
            consolidate_batch=int(d.get("consolidate_batch", 10)),
            consolidate_interval_days=int(d.get("consolidate_interval_days", 1)),
            max_consolidate_tokens=int(d.get("max_consolidate_tokens", 500)),
        )
