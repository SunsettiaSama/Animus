from __future__ import annotations

from agent.soul.memory.emergence import Emergence
from agent.soul.memory.graph.networks.event.network import EventMemoryNetwork
from agent.soul.memory.graph.networks.social.network import SocialMemoryNetwork
from agent.soul.memory.rumination import RuminationService
from agent.soul.memory.sleep.types import SleepConfig, SleepResult
from config.soul.memory.service_config import MemoryServiceConfig


class SleepService:
    """睡眠期巩固：遗忘扫描、聚类重建、高情绪记忆 → 反刍 buffer、缓冲衰减。"""

    def __init__(
        self,
        event: EventMemoryNetwork,
        social: SocialMemoryNetwork,
        emergence: Emergence,
        rumination: RuminationService,
        cfg: MemoryServiceConfig,
        *,
        sleep_cfg: SleepConfig | None = None,
    ) -> None:
        self._event = event
        self._social = social
        self._emergence = emergence
        self._rumination = rumination
        self._cfg = cfg
        self._sleep_cfg = sleep_cfg or SleepConfig()

    def run(
        self,
        *,
        tick_id: str = "",
        dry_run: bool = False,
        forget_threshold: float | None = None,
    ) -> SleepResult:
        resolved_threshold = (
            forget_threshold
            if forget_threshold is not None
            else self._cfg.forget_threshold
        )
        forgotten_ids: list[str] = []
        event_ids: list[str] = []
        social_ids: list[str] = []

        if self._sleep_cfg.run_forget:
            event_ids = self._event.forget_scan(resolved_threshold, dry_run)
            social_ids = self._social.forget_scan(
                resolved_threshold,
                self._cfg.half_life_days,
                dry_run=dry_run,
            )
            forgotten_ids = list(dict.fromkeys(event_ids + social_ids))

        cluster_rebuilt = False
        if self._sleep_cfg.rebuild_cluster:
            self._emergence.spread.schedule_cluster_rebuild()
            cluster_rebuilt = True

        rumination_fed = 0
        rumination_fed_ids: list[str] = []
        if self._sleep_cfg.feed_rumination_buffer:
            sleep_tick = f"sleep:{tick_id}" if tick_id else "sleep"
            rumination_fed, rumination_fed_ids = self._rumination.consolidate_from_sleep(
                tick_id=sleep_tick,
                scan_limit=self._sleep_cfg.consolidation_scan_limit,
                emotion_threshold=self._sleep_cfg.sleep_emotion_threshold,
            )

        buffer_pruned = 0
        if self._sleep_cfg.prune_rumination_buffer:
            buffer_pruned = self._rumination.buffer.decay_and_prune(
                decay=self._sleep_cfg.buffer_decay,
                drop_below=self._sleep_cfg.buffer_drop_below,
            )

        return SleepResult(
            tick_id=tick_id,
            forgotten_ids=forgotten_ids,
            event_forgotten=len(event_ids),
            social_forgotten=len(social_ids),
            cluster_rebuilt=cluster_rebuilt,
            buffer_pruned=buffer_pruned,
            buffer_size=len(self._rumination.buffer),
            rumination_fed=rumination_fed,
            rumination_fed_ids=rumination_fed_ids,
        )

    def tick(self, snapshot) -> SleepResult:
        tid = getattr(snapshot, "tick_id", "") or ""
        return self.run(tick_id=tid)
