from __future__ import annotations

from config.agent.memory.milestone_config import MilestoneConfig
from ...memory.milestone.memory import MilestoneMemory
from ...memory.milestone.store import MilestoneStore, load_store


def make_milestone(
    cfg: MilestoneConfig,
    llm=None,
) -> MilestoneMemory:
    store = load_store(cfg) if cfg.enabled else MilestoneStore(entries=[], cfg=cfg)
    return MilestoneMemory(store=store, cfg=cfg, llm=llm)


__all__ = ["make_milestone"]
