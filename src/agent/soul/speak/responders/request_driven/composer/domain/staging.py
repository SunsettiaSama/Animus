from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from random import Random

from ..ports.clock import ClockPort, MonotonicClock
from ..ports.memory import MemoryHint, MemorySearchPort, MemoryUnit, NullMemorySearchPort
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
    by_id: dict[str, StagedMemory] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    turn_index: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock)
    load_generation: int = 0
    warming: bool = False
    pending: int = 0


class MemoryStagingBuffer:
    """按 unit_id 离散暂存；装入检索异步，不阻塞主流程。"""

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
        sid = session_id.strip()
        state = self._sessions.get(sid)
        if state is None:
            return
        with state.lock:
            state.load_generation += 1
            state.by_id.clear()
            state.order.clear()
            state.warming = False
            state.pending = 0
        self._sessions.pop(sid, None)

    def is_warming(self, session_id: str) -> bool:
        state = self._sessions.get(session_id.strip())
        if state is None:
            return False
        with state.lock:
            return bool(state.warming or state.pending > 0)

    def wait_pending(self, session_id: str, *, timeout: float = 2.0) -> bool:
        """测试/同步点：等待异步装入结束。"""
        sid = session_id.strip()
        deadline = self._clock.now() + max(0.0, float(timeout))
        while self._clock.now() < deadline:
            if not self.is_warming(sid):
                return True
            threading.Event().wait(0.02)
        return not self.is_warming(sid)

    def items(self, session_id: str) -> list[StagedMemory]:
        state = self._session(session_id)
        with state.lock:
            self._evict_locked(state)
            return [state.by_id[uid] for uid in state.order if uid in state.by_id]

    def get_unit(self, session_id: str, unit_id: str) -> MemoryUnit | None:
        uid = unit_id.strip()
        if not uid:
            return None
        state = self._session(session_id)
        with state.lock:
            item = state.by_id.get(uid)
            return item.unit if item is not None else None

    def list_units(self, session_id: str) -> list[MemoryUnit]:
        return [item.unit for item in self.items(session_id)]

    def seed_init(self, session_id: str, *, query_text: str = "") -> list[MemoryUnit]:
        """init：立即返回；检索在后台装入（80% share / 20% 乱跳）。"""
        sid = session_id.strip()
        state = self._session(sid)
        with state.lock:
            state.turn_index = 0
            state.by_id.clear()
            state.order.clear()
            generation = state.load_generation + 1
            state.load_generation = generation
            state.warming = True
            state.pending += 1
            roll = self._rng.random()
        if roll < self._related_ratio:
            hint_q = self._share_hint.share_query_text(sid).strip() or query_text.strip()
            query = hint_q or "share"
            hint: MemoryHint = "share"
            kind = "share"
        else:
            query = query_text.strip() or "random"
            hint = "random"
            kind = "random"
        self._spawn_load(
            sid,
            generation=generation,
            query=query,
            hint=hint,
            kind=kind,
            clear_warming=True,
        )
        return []

    def stage_in(
        self,
        session_id: str,
        query_text: str,
        *,
        turn_index: int | None = None,
    ) -> list[MemoryUnit]:
        """对话深入：异步装入，立刻返回当前库存。"""
        sid = session_id.strip()
        state = self._session(sid)
        with state.lock:
            if turn_index is not None:
                state.turn_index = max(state.turn_index, int(turn_index))
            else:
                state.turn_index += 1
            self._evict_locked(state)
            generation = state.load_generation
            state.pending += 1
            current = [state.by_id[uid].unit for uid in state.order if uid in state.by_id]
            roll = self._rng.random()
        if roll < self._related_ratio:
            query = query_text.strip()
            hint: MemoryHint = "related"
            kind = "related"
        else:
            query = query_text.strip() or "random"
            hint = "random"
            kind = "random"
        self._spawn_load(
            sid,
            generation=generation,
            query=query,
            hint=hint,
            kind=kind,
            clear_warming=False,
        )
        return current

    def ingest_units(
        self,
        session_id: str,
        units: list[MemoryUnit],
        *,
        kind: str = "trajectory",
    ) -> None:
        """同步写入离散 unit（不经上游检索）。"""
        sid = session_id.strip()
        if not units:
            return
        state = self._session(sid)
        with state.lock:
            self._evict_locked(state)
            self._ingest_locked(state, units, kind=kind)

    def remove_unit(self, session_id: str, unit_id: str) -> bool:
        sid = session_id.strip()
        uid = unit_id.strip()
        if not uid:
            return False
        state = self._session(sid)
        with state.lock:
            if uid not in state.by_id:
                return False
            del state.by_id[uid]
            state.order = [x for x in state.order if x != uid]
            return True

    def upsert_unit_embedding(
        self,
        session_id: str,
        unit_id: str,
        embedding: list[float] | tuple[float, ...],
    ) -> bool:
        uid = unit_id.strip()
        if not uid or not embedding:
            return False
        state = self._session(session_id)
        with state.lock:
            item = state.by_id.get(uid)
            if item is None:
                return False
            state.by_id[uid] = StagedMemory(
                unit=item.unit.with_embedding(embedding),
                loaded_at=item.loaded_at,
                loaded_turn=item.loaded_turn,
                kind=item.kind,
            )
            return True

    def _spawn_load(
        self,
        session_id: str,
        *,
        generation: int,
        query: str,
        hint: MemoryHint,
        kind: str,
        clear_warming: bool,
    ) -> None:
        def work() -> None:
            units = self._memory.search_related(
                session_id,
                query,
                limit=self._stage_in_limit,
                hint=hint,
            )
            state = self._session(session_id)
            with state.lock:
                if state.load_generation != generation:
                    state.pending = max(0, state.pending - 1)
                    return
                self._ingest_locked(state, units, kind=kind)
                state.pending = max(0, state.pending - 1)
                if clear_warming and state.pending == 0:
                    state.warming = False
                elif not clear_warming and state.pending == 0:
                    state.warming = False

        threading.Thread(
            target=work,
            name=f"mem-stage-{session_id[:8]}-{kind}",
            daemon=True,
        ).start()

    def _session(self, session_id: str) -> _SessionStaging:
        sid = session_id.strip()
        state = self._sessions.get(sid)
        if state is None:
            state = _SessionStaging()
            self._sessions[sid] = state
        return state

    def _ingest_locked(
        self,
        state: _SessionStaging,
        units: list[MemoryUnit],
        *,
        kind: str,
    ) -> None:
        now = self._clock.now()
        for unit in filter_utterance_units(units, kind=kind):
            uid = unit.unit_id.strip()
            if not uid:
                continue
            existing = state.by_id.get(uid)
            if existing is not None:
                merged = MemoryUnit(
                    unit_id=uid,
                    text=unit.text or existing.unit.text,
                    source=unit.source or existing.unit.source,
                    score=max(unit.score, existing.unit.score),
                    embedding=unit.embedding or existing.unit.embedding,
                    meta={**existing.unit.meta, **unit.meta},
                )
                state.by_id[uid] = StagedMemory(
                    unit=merged,
                    loaded_at=existing.loaded_at,
                    loaded_turn=existing.loaded_turn,
                    kind=kind or existing.kind,
                )
                continue
            state.by_id[uid] = StagedMemory(
                unit=unit,
                loaded_at=now,
                loaded_turn=state.turn_index,
                kind=kind,
            )
            state.order.append(uid)
        overflow = len(state.order) - self._max_items
        if overflow > 0:
            drop = state.order[:overflow]
            state.order = state.order[overflow:]
            for uid in drop:
                state.by_id.pop(uid, None)

    def _evict_locked(self, state: _SessionStaging) -> None:
        now = self._clock.now()
        kept: list[str] = []
        for uid in state.order:
            item = state.by_id.get(uid)
            if item is None:
                continue
            age_turns = state.turn_index - item.loaded_turn
            age_sec = now - item.loaded_at
            if age_turns > self._max_turn_age:
                state.by_id.pop(uid, None)
                continue
            if age_sec > self._ttl_sec:
                state.by_id.pop(uid, None)
                continue
            kept.append(uid)
        state.order = kept
