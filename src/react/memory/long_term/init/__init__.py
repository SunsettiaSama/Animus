from __future__ import annotations

import json
import os

from config.react.memory.memory_config import LongTermMemoryConfig
from react.memory.long_term.memory import LongTermMemory
from react.memory.long_term.store import MEMORIES_FILE, LongTermStore, MemoryEntry


def load_store(cfg: LongTermMemoryConfig) -> LongTermStore:
    entries: list[MemoryEntry] = []
    json_path = os.path.join(cfg.memory_dir, MEMORIES_FILE)
    if os.path.exists(json_path):
        with open(json_path, encoding="utf-8") as f:
            entries = [MemoryEntry(**item) for item in json.load(f)]
    return LongTermStore(entries=entries, cfg=cfg)


def init_empty_store(cfg: LongTermMemoryConfig) -> LongTermStore:
    return LongTermStore(entries=[], cfg=cfg)


def make_memory(cfg: LongTermMemoryConfig) -> LongTermMemory:
    store = load_store(cfg) if cfg.load_from_disk else init_empty_store(cfg)
    return LongTermMemory(store, cfg)


__all__ = ["load_store", "init_empty_store", "make_memory"]
