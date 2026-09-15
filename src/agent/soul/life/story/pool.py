"""life.story.pool — 演绎预跑池（R9 预约轴版）。

编剧在到点前（默认 T-1h）把预约轴上的地标演化为完整 beat 草稿入池；
排程器每拍只做零等待的到点出货（``pop_due``）。护栏：
- 池深即预算（``max_depth``）——预跑烧 token，超限不再吸收新演化；
- 同一 landmark 只入池一次（确定性 beat_id 之外的二级防线）；
- ``drop_pending`` 供导演在用户轮高显著信号后整池重估（R9 失效）。

池为进程内态（R10 现状记账同款）：重启即失，失而复得靠演化过场
（已 done 地标的 narrative 持久化在手账，echo 路径零成本重出稿）。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PoolEntry:
    """一件预跑稿：到点即投的完整 beat + 呈现元数据。"""

    draft: Any                          # BeatDraft（frozen dataclass，不 import 防 cir）
    landmark_id: str
    card_id: str
    deliver_at: float                   # epoch 秒：预约轴上的开口时刻
    intention: str = ""
    scheduled_at: str = ""              # ISO；前端预告与落账的剧情时间
    evolved_at: float = 0.0


@dataclass
class _PoolState:
    entries: dict[str, PoolEntry] = field(default_factory=dict)


class EvolutionPool:
    """线程安全的预跑池：演化线程入池，排程线程到点出货。"""

    def __init__(self, *, max_depth: int = 4) -> None:
        self._lock = threading.Lock()
        self._state = _PoolState()
        self._max_depth = max(1, int(max_depth))

    # ── 入池 / 查询 ────────────────────────────────────────────────────────

    def put(self, entry: PoolEntry) -> bool:
        """入池；同 landmark 重复或超预算时拒绝（返回 False）。"""
        with self._lock:
            if entry.landmark_id in self._state.entries:
                return False
            if len(self._state.entries) >= self._max_depth:
                return False
            self._state.entries[entry.landmark_id] = entry
            return True

    def has(self, landmark_id: str) -> bool:
        with self._lock:
            return landmark_id in self._state.entries

    def has_capacity(self) -> bool:
        with self._lock:
            return len(self._state.entries) < self._max_depth

    def pending_landmark_ids(self) -> set[str]:
        with self._lock:
            return set(self._state.entries)

    # ── 出货 / 失效 ────────────────────────────────────────────────────────

    def pop_due(self, now: float) -> list[PoolEntry]:
        """deliver_at 到点（含已过期未投）的条目按时间升序出货。"""
        with self._lock:
            due_ids = [
                lid for lid, e in self._state.entries.items()
                if e.deliver_at <= now
            ]
            due = [self._state.entries.pop(lid) for lid in due_ids]
        due.sort(key=lambda e: e.deliver_at)
        return due

    def future_by_card(self, card_id: str, now: float) -> list[PoolEntry]:
        """某卡片尚未到点的预跑稿（升序）——进度段 upcoming 的素材。"""
        with self._lock:
            entries = [
                e for e in self._state.entries.values()
                if e.card_id == card_id and e.deliver_at > now
            ]
        entries.sort(key=lambda e: e.deliver_at)
        return list(entries)

    def drop_pending(self) -> int:
        """整池清空（导演失效重估：剧情走向已被用户显著改变）。"""
        with self._lock:
            dropped = len(self._state.entries)
            self._state.entries.clear()
            return dropped
