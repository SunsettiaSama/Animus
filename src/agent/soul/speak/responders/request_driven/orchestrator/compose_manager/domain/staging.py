from __future__ import annotations

import threading
from dataclasses import dataclass, field
from random import Random

from ..ports.clock import ClockPort, MonotonicClock
from ..ports.memory import MemorySearchPort, MemoryUnit, NullMemorySearchPort
from ..ports.share_hint import NullShareHintPort, ShareHintPort
from .utterance import filter_utterance_units


@dataclass
class StagedMemory:
    unit: MemoryUnit
    loaded_at: float
    loaded_turn: int
    kind: str = "related"


@dataclass
class _SessionStaging:
    items: list[StagedMemory] = field(default_factory=list)
    turn_index: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock)


class MemoryStagingBuffer:
    """动态暂存记忆：从记忆系统装入 + 时间/轮次淘汰 + 80/20 扰动装入。"""

    def __init__(
        self,
        *,
        memory_search: MemorySearchPort | None = None,
        share_hint: ShareHintPort | None = None,
        clock: ClockPort | None = None,
        rng: Random | None = None,
        max_items: int = 32,
        max_turn_age: int = 24,
        ttl_sec: float = 1800.0,
        related_ratio: float = 0.80,
        stage_in_limit: int = 6,
    ) -> None:
        self._memory = memory_search or NullMemorySearchPort()
        self._share_hint = share_hint or NullShareHintPort()
        self._clock = clock or MonotonicClock()
        self._rng = rng or Random()
        self._max_items = max(1, max_items)
        self._max_turn_age = max(1, max_turn_age)
        self._ttl_sec = max(1.0, ttl_sec)
        self._related_ratio = min(1.0, max(0.0, related_ratio))
        self._stage_in_limit = max(1, stage_in_limit)
        self._sessions: dict[str, _SessionStaging] = {}

    def set_memory_search(self, port: MemorySearchPort) -> None:
        self._memory = port

    def set_share_hint(self, port: ShareHintPort) -> None:
        self._share_hint = port

    def reset_session(self, session_id: str) -> None:
        self._sessions.pop(session_id.strip(), None)

    def items(self, session_id: str) -> list[StagedMemory]:
        state = self._session(session_id)
        with state.lock:
            self._evict_locked(state)
            return list(state.items)

    def seed_init(self, session_id: str, *, query_text: str = "") -> list[MemoryUnit]:
        """init：80% share 相关 / 20% 乱跳。"""
        sid = session_id.strip()
        state = self._session(sid)
        with state.lock:
            state.turn_index = 0
            state.items.clear()
            roll = self._rng.random()
            if roll < self._related_ratio:
                hint_q = self._share_hint.share_query_text(sid).strip() or query_text.strip()
                units = self._memory.search_related(
                    sid,
                    hint_q or "share",
                    limit=self._stage_in_limit,
                    hint="share",
                )
                kind = "share"
            else:
                units = self._memory.search_related(
                    sid,
                    query_text.strip() or "random",
                    limit=self._stage_in_limit,
                    hint="random",
                )
                kind = "random"
            self._ingest_locked(state, units, kind=kind)
            return [item.unit for item in state.items]

    def stage_in(self, session_id: str, query_text: str, *, turn_index: int | None = None) -> list[MemoryUnit]:
        """对话深入时装入：80% related / 20% 扰动。"""
        sid = session_id.strip()
        state = self._session(sid)
        with state.lock:
            if turn_index is not None:
                state.turn_index = max(state.turn_index, int(turn_index))
            else:
                state.turn_index += 1
            self._evict_locked(state)
            roll = self._rng.random()
            if roll < self._related_ratio:
                units = self._memory.search_related(
                    sid,
                    query_text.strip(),
                    limit=self._stage_in_limit,
                    hint="related",
                )
                kind = "related"
            else:
                units = self._memory.search_related(
                    sid,
                    query_text.strip() or "random",
                    limit=self._stage_in_limit,
                    hint="random",
                )
                kind = "random"
            self._ingest_locked(state, units, kind=kind)
            return [item.unit for item in state.items]

    def ingest_units(
        self,
        session_id: str,
        units: list[MemoryUnit],
        *,
        kind: str = "trajectory",
    ) -> None:
        """直接写入暂存（不经上游检索 / 80-20），供轨迹压缩产物回流。"""
        sid = session_id.strip()
        if not units:
            return
        state = self._session(sid)
        with state.lock:
            self._evict_locked(state)
            self._ingest_locked(state, units, kind=kind)

    def remove_unit(self, session_id: str, unit_id: str) -> bool:
        """按 unit_id 从暂存删除一条；供导演有限干预。"""
        sid = session_id.strip()
        uid = unit_id.strip()
        if not uid:
            return False
        state = self._session(sid)
        with state.lock:
            before = len(state.items)
            state.items = [item for item in state.items if item.unit.unit_id != uid]
            return len(state.items) < before

    def _session(self, session_id: str) -> _SessionStaging:
        sid = session_id.strip()
        state = self._sessions.get(sid)
        if state is None:
            state = _SessionStaging()
            self._sessions[sid] = state
        return state

    def _ingest_locked(self, state: _SessionStaging, units: list[MemoryUnit], *, kind: str) -> None:
        now = self._clock.now()
        seen = {item.unit.unit_id for item in state.items}
        for unit in filter_utterance_units(units, kind=kind):
            uid = unit.unit_id.strip()
            if not uid or uid in seen:
                continue
            state.items.append(
                StagedMemory(
                    unit=unit,
                    loaded_at=now,
                    loaded_turn=state.turn_index,
                    kind=kind,
                )
            )
            seen.add(uid)
        overflow = len(state.items) - self._max_items
        if overflow > 0:
            state.items = state.items[overflow:]

    def _evict_locked(self, state: _SessionStaging) -> None:
        now = self._clock.now()
        kept: list[StagedMemory] = []
        for item in state.items:
            age_turns = state.turn_index - item.loaded_turn
            age_sec = now - item.loaded_at
            if age_turns > self._max_turn_age:
                continue
            if age_sec > self._ttl_sec:
                continue
            kept.append(item)
        state.items = kept
