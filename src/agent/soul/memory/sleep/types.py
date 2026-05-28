from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SleepConfig:
    buffer_decay: float = 0.85
    buffer_drop_below: float = 0.08
    prune_rumination_buffer: bool = True
    feed_rumination_buffer: bool = True
    consolidation_scan_limit: int = 500
    sleep_emotion_threshold: float = 0.55
    rebuild_cluster: bool = True
    run_forget: bool = True


@dataclass
class SleepResult:
    tick_id: str = ""
    forgotten_ids: list[str] = field(default_factory=list)
    event_forgotten: int = 0
    social_forgotten: int = 0
    cluster_rebuilt: bool = False
    buffer_pruned: int = 0
    buffer_size: int = 0
    rumination_fed: int = 0
    rumination_fed_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "tick_id": self.tick_id,
            "forgotten_count": len(self.forgotten_ids),
            "forgotten_ids": list(self.forgotten_ids),
            "event_forgotten": self.event_forgotten,
            "social_forgotten": self.social_forgotten,
            "cluster_rebuilt": self.cluster_rebuilt,
            "buffer_pruned": self.buffer_pruned,
            "buffer_size": self.buffer_size,
            "rumination_fed": self.rumination_fed,
            "rumination_fed_ids": list(self.rumination_fed_ids),
        }
