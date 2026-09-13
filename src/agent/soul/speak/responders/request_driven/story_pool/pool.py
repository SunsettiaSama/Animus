"""剧情材料池：候选大纲条目管理 + 活体剧情快照存取。

职责边界：
- 本模块管理"候选条目"的新鲜度、选取、水位与失效；
- 持久化委托 StoryPoolStore；生成委托 StoryPrewarmer；
- 不理解 session 生命周期，不持有 LLM。

条目内容是 state.core 对象的 snapshot() dict，注入时经 from_dict 还原。
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from .freshness import FreshnessLevel, pool_entry_policy
from .store import PoolFile, StoryPoolStore

# 池内最多保留的候选条目（含骨架）；超出时淘汰最旧
MAX_POOL_ENTRIES = 3


@dataclass
class StoryPoolEntry:
    """一条预载候选：完整的新开场（大纲 + 场记 + 临场卡 + 开场旁白）。"""

    entry_id: str
    created_at: float
    full: bool                 # True=编剧 Agent 全量；False=启发式骨架
    plot_arc: dict[str, Any]
    plot_flow: dict[str, Any]
    presence_card: dict[str, Any]
    narrative_card: dict[str, Any]
    opening: str = ""
    seed_note: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "created_at": float(self.created_at),
            "full": bool(self.full),
            "plot_arc": self.plot_arc,
            "plot_flow": self.plot_flow,
            "presence_card": self.presence_card,
            "narrative_card": self.narrative_card,
            "opening": self.opening,
            "seed_note": self.seed_note,
            "meta": dict(self.meta),
        }

    @classmethod
    def from_dict(cls, raw: object) -> StoryPoolEntry | None:
        if not isinstance(raw, dict):
            return None
        arc = raw.get("plot_arc")
        if not isinstance(arc, dict):
            return None
        return cls(
            entry_id=str(raw.get("entry_id") or uuid.uuid4().hex[:10]),
            created_at=float(raw.get("created_at") or 0.0),
            full=bool(raw.get("full")),
            plot_arc=arc,
            plot_flow=raw.get("plot_flow") if isinstance(raw.get("plot_flow"), dict) else {},
            presence_card=(
                raw.get("presence_card") if isinstance(raw.get("presence_card"), dict) else {}
            ),
            narrative_card=(
                raw.get("narrative_card") if isinstance(raw.get("narrative_card"), dict) else {}
            ),
            opening=str(raw.get("opening") or ""),
            seed_note=str(raw.get("seed_note") or ""),
            meta=raw.get("meta") if isinstance(raw.get("meta"), dict) else {},
        )


class StoryMaterialPool:
    """按 key（session/channel 身份）组织的剧情候选池。"""

    def __init__(self, store: StoryPoolStore, *, max_entries: int = MAX_POOL_ENTRIES) -> None:
        self._store = store
        self._max = max(1, int(max_entries))
        self._lock = threading.Lock()

    # ── 查询 ───────────────────────────────────────────────────────────────

    def fresh_entries(self, key: str, *, now: float | None = None) -> list[StoryPoolEntry]:
        """返回未过期条目（新→旧）；过期条目顺手清除。"""
        now = time.time() if now is None else now
        policy = pool_entry_policy()
        with self._lock:
            file = self._store.load(key)
            fresh: list[StoryPoolEntry] = []
            kept: list[dict[str, Any]] = []
            changed = False
            for raw in file.entries:
                entry = StoryPoolEntry.from_dict(raw)
                if entry is None:
                    changed = True
                    continue
                level: FreshnessLevel = policy.classify(
                    created_at=entry.created_at, now=now
                )
                if level == "fresh":
                    fresh.append(entry)
                    kept.append(entry.to_dict())
                else:
                    changed = True
            if changed:
                file.entries = kept
                self._store.save(key, file)
            return fresh

    def fresh_count(self, key: str) -> int:
        return len(self.fresh_entries(key))

    # ── 写入 ───────────────────────────────────────────────────────────────

    def replace_candidates(
        self, key: str, entries: list[StoryPoolEntry]
    ) -> None:
        """整体替换候选（预热器产出后调用）；池不与旧条目混装，避免同屏多版剧情。"""
        now = time.time()
        payload = []
        for entry in entries[: self._max]:
            if entry.created_at <= 0:
                entry.created_at = now
            payload.append(entry.to_dict())
        with self._lock:
            file = self._store.load(key)
            file.entries = payload
            self._store.save(key, file)

    # ── 消费 ───────────────────────────────────────────────────────────────

    def take_freshest(self, key: str, *, consume: bool = True) -> StoryPoolEntry | None:
        """取最优候选：全量（Agent 级）优先，同级取最新；consume=True 清空候选。"""
        fresh = self.fresh_entries(key)
        if not fresh:
            return None
        entry = max(fresh, key=lambda e: (e.full, e.created_at))
        if consume:
            with self._lock:
                file = self._store.load(key)
                file.entries = []
                self._store.save(key, file)
        return entry

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._store.drop(key)

    # ── 活体剧情快照（重启续写） ────────────────────────────────────────────

    def save_live(self, key: str, snapshot: dict[str, Any]) -> None:
        """剧情状态写透（opening/剧情文本随 state 快照）。"""
        with self._lock:
            file = self._store.load(key)
            file.live = dict(snapshot)
            self._store.save(key, file)

    def load_live(self, key: str) -> dict[str, Any] | None:
        """恢复未过期的活体剧情快照；过期返回 None 并顺手清除。"""
        now = time.time()
        from .freshness import live_snapshot_policy

        policy = live_snapshot_policy()
        with self._lock:
            file = self._store.load(key)
            live = file.live
        if not isinstance(live, dict):
            return None
        created = float(live.get("created_at") or 0.0)
        if policy.classify(created_at=created, now=now) != "fresh":
            with self._lock:
                file.live = None
                self._store.save(key, file)
            return None
        return live
