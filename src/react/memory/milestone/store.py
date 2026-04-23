from __future__ import annotations

import json
import os
from dataclasses import asdict

from config.react.memory.milestone_config import MilestoneConfig
from react.memory.milestone.entry import MilestoneEntry

MILESTONES_FILE = "milestones.json"


class MilestoneStore:
    def __init__(self, entries: list[MilestoneEntry], cfg: MilestoneConfig) -> None:
        self._entries = entries
        self._cfg = cfg

    def add(self, entry: MilestoneEntry) -> list[MilestoneEntry]:
        """Append *entry* and evict lowest-importance entries when over capacity.

        Returns the list of evicted entries (may be empty) so callers can
        migrate them to L3 long-term memory.
        """
        self._entries.append(entry)
        evicted: list[MilestoneEntry] = []
        if len(self._entries) > self._cfg.max_milestones:
            # Sort ascending by importance; lowest scores get evicted first.
            self._entries.sort(key=lambda e: e.importance)
            overflow = len(self._entries) - self._cfg.max_milestones
            evicted = self._entries[:overflow]
            self._entries = self._entries[overflow:]
        return evicted

    def save(self) -> None:
        os.makedirs(self._cfg.milestone_dir, exist_ok=True)
        path = os.path.join(self._cfg.milestone_dir, MILESTONES_FILE)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([asdict(e) for e in self._entries], f, ensure_ascii=False, indent=2)

    @property
    def entries(self) -> list[MilestoneEntry]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)


def load_store(cfg: MilestoneConfig) -> MilestoneStore:
    path = os.path.join(cfg.milestone_dir, MILESTONES_FILE)
    entries: list[MilestoneEntry] = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            entries = [MilestoneEntry(**item) for item in json.load(f)]
    return MilestoneStore(entries=entries, cfg=cfg)
