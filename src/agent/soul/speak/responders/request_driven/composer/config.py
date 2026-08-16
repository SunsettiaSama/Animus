from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ComposeManagerConfig:
    """ComposeManager 可配置常数；禁止魔法数散落。"""

    enabled: bool = False
    compress_chunk_size: int = 4
    staging_max_items: int = 32
    staging_max_turn_age: int = 24
    staging_ttl_sec: float = 1800.0
    stage_in_related_ratio: float = 0.80
    retrieve_normal_ratio: float = 0.90
    bm25_min_score: float = 0.0
    bm25_top_k: int = 3
    stage_in_limit: int = 6
    history_query_turns: int = 4
    rng_seed: int | None = None
    # 导演对共享 staging 的干预条数上限（inject 或 remove 合计）
    director_memory_intervene_max: int = 1
    director_bm25_top_k: int = 3
