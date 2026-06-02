from __future__ import annotations

import math
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from agent.soul.memory.emergence.line_dedup import (
    dedupe_memory_line_pairs,
    memory_line_body_key,
)
from agent.soul.speak.orchestrator.guidance.memory.pick_weights import (
    PICK_PENALTY_FACTOR,
    PICK_WEIGHT_DEFAULT,
    PICK_WEIGHT_FLOOR,
)

MemoryBufferSource = Literal["emergence", "keyword", "social_prefetch", "warm_spread"]


@dataclass(frozen=True)
class MemoryBufferItem:
    turn_index: int
    lines: tuple[str, ...]
    unit_ids: tuple[str, ...]
    source: MemoryBufferSource
    ready: bool = True


@dataclass
class MemoryComposePullResult:
    inject_lines: list[str] = field(default_factory=list)
    inject_unit_ids: list[str] = field(default_factory=list)
    inject_turn_indices: list[int] = field(default_factory=list)
    social_prefetch_lines: list[str] = field(default_factory=list)
    social_prefetch_unit_ids: list[str] = field(default_factory=list)
    warm_spread_lines: list[str] = field(default_factory=list)
    warm_spread_unit_ids: list[str] = field(default_factory=list)
    merge_ratio: float = 0.0
    keyword_wait_ms: int = 0
    sources: list[str] = field(default_factory=list)
    spilled_lines: list[str] = field(default_factory=list)
    spilled_unit_ids: list[str] = field(default_factory=list)


# 兼容旧引用
MemoryQueueItem = MemoryBufferItem


@dataclass
class MemoryQueueConsumeResult:
    inject_lines: list[str] = field(default_factory=list)
    inject_unit_ids: list[str] = field(default_factory=list)
    inject_turn_index: int = 0
    spilled_lines: list[str] = field(default_factory=list)
    spilled_unit_ids: list[str] = field(default_factory=list)
    spilled_turn_index: int = 0


class SessionMemoryBuffer:
    """Speak compose 记忆 buffer：分区 slot + 按轮次缓存 + 双通道 merge。"""

    def __init__(self, *, max_turn_gap: int = 3) -> None:
        self._max_turn_gap = max(1, max_turn_gap)
        self._turn_queues: dict[str, deque[MemoryBufferItem]] = {}
        self._social_prefetch: dict[str, MemoryBufferItem] = {}
        self._warm_spread: dict[str, MemoryBufferItem] = {}
        self._consumed_unit_ids: dict[str, set[str]] = {}
        self._recall_pick_multiplier: dict[str, dict[str, float]] = {}
        self._waiters: dict[str, threading.Condition] = {}
        self._waiters_lock = threading.Lock()

    def mark_unit_consumed(self, session_id: str, unit_id: str) -> None:
        uid = unit_id.strip()
        if not uid:
            return
        self._consumed_unit_ids.setdefault(session_id, set()).add(uid)

    def recall_pick_weight(self, session_id: str, unit_id: str) -> float:
        uid = unit_id.strip()
        if not uid:
            return PICK_WEIGHT_DEFAULT
        return self._recall_pick_multiplier.get(session_id, {}).get(uid, PICK_WEIGHT_DEFAULT)

    def record_recall_pick(self, session_id: str, unit_id: str) -> None:
        uid = unit_id.strip()
        if not uid:
            return
        table = self._recall_pick_multiplier.setdefault(session_id, {})
        prev = table.get(uid, PICK_WEIGHT_DEFAULT)
        table[uid] = max(PICK_WEIGHT_FLOOR, prev * PICK_PENALTY_FACTOR)

    def _is_consumed(self, session_id: str, unit_id: str) -> bool:
        return unit_id.strip() in self._consumed_unit_ids.get(session_id, set())

    def _condition(self, session_id: str) -> threading.Condition:
        with self._waiters_lock:
            cond = self._waiters.get(session_id)
            if cond is None:
                cond = threading.Condition()
                self._waiters[session_id] = cond
            return cond

    def _queue(self, session_id: str) -> deque[MemoryBufferItem]:
        if session_id not in self._turn_queues:
            self._turn_queues[session_id] = deque()
        return self._turn_queues[session_id]

    def enqueue_turn(self, session_id: str, item: MemoryBufferItem) -> None:
        if not item.unit_ids and not item.lines:
            return
        if item.source == "keyword" and not item.lines:
            return
        if item.source == "emergence" and not item.ready:
            return

        queue = self._queue(session_id)
        filtered = deque(
            existing
            for existing in queue
            if not (existing.turn_index == item.turn_index and existing.source == item.source)
        )
        filtered.append(item)
        self._turn_queues[session_id] = filtered
        with self._condition(session_id):
            self._condition(session_id).notify_all()

    def set_social_prefetch(self, session_id: str, item: MemoryBufferItem) -> None:
        if not item.unit_ids:
            return
        self._social_prefetch[session_id] = item

    def set_warm_spread(self, session_id: str, item: MemoryBufferItem) -> None:
        if not item.unit_ids:
            return
        self._warm_spread[session_id] = item

    def consume_warm_spread(self, session_id: str) -> MemoryBufferItem | None:
        return self._warm_spread.pop(session_id, None)

    def has_turn_source(
        self,
        session_id: str,
        turn_index: int,
        source: MemoryBufferSource,
    ) -> bool:
        queue = self._turn_queues.get(session_id)
        if not queue:
            return False
        return any(
            item.turn_index == turn_index and item.source == source
            for item in queue
        )

    def wait_for_turn_source(
        self,
        session_id: str,
        turn_index: int,
        source: MemoryBufferSource,
        timeout_ms: int,
    ) -> bool:
        if timeout_ms <= 0:
            return self.has_turn_source(session_id, turn_index, source)
        deadline = time.monotonic() + timeout_ms / 1000.0
        cond = self._condition(session_id)
        with cond:
            while not self.has_turn_source(session_id, turn_index, source):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                cond.wait(timeout=remaining)
            return True

    def _take_turn_item(
        self,
        session_id: str,
        turn_index: int,
        source: MemoryBufferSource,
    ) -> MemoryBufferItem | None:
        queue = self._turn_queues.get(session_id)
        if not queue:
            return None
        kept: deque[MemoryBufferItem] = deque()
        found: MemoryBufferItem | None = None
        for item in queue:
            if (
                item.turn_index == turn_index
                and item.source == source
                and found is None
            ):
                found = item
            else:
                kept.append(item)
        self._turn_queues[session_id] = kept
        return found

    def _trim_stale(self, session_id: str, current_turn_index: int) -> list[MemoryBufferItem]:
        queue = self._turn_queues.get(session_id)
        if not queue:
            return []
        kept: deque[MemoryBufferItem] = deque()
        spilled: list[MemoryBufferItem] = []
        for item in queue:
            gap = abs(item.turn_index - current_turn_index)
            if item.source == "keyword":
                if item.turn_index == current_turn_index:
                    kept.append(item)
                continue
            if gap < self._max_turn_gap and item.source == "emergence":
                kept.append(item)
            elif item.source == "emergence":
                spilled.append(item)
        self._turn_queues[session_id] = kept
        return spilled

    def pull_for_compose(
        self,
        session_id: str,
        current_turn_index: int,
        *,
        keyword_wait_ms: int = 200,
        budget: int = 5,
        merge_ratio: float | None = None,
    ) -> MemoryComposePullResult:
        ratio = merge_ratio if merge_ratio is not None else random.random()
        ratio = max(0.0, min(1.0, ratio))
        budget = max(1, budget)

        if keyword_wait_ms > 0:
            self.wait_for_turn_source(
                session_id,
                current_turn_index,
                "keyword",
                keyword_wait_ms,
            )

        spilled = self._trim_stale(session_id, current_turn_index)
        keyword_item = self._take_turn_item(
            session_id,
            current_turn_index,
            "keyword",
        )

        queue = self._turn_queues.get(session_id, deque())
        emergence_past: list[MemoryBufferItem] = []
        emergence_current: MemoryBufferItem | None = None
        for item in list(queue):
            if item.source != "emergence":
                continue
            if item.turn_index == current_turn_index:
                emergence_current = item
            elif abs(item.turn_index - current_turn_index) < self._max_turn_gap:
                emergence_past.append(item)

        keyword_lines = list(keyword_item.lines) if keyword_item else []
        keyword_ids = list(keyword_item.unit_ids) if keyword_item else []

        past_lines: list[str] = []
        past_ids: list[str] = []
        past_turns: list[int] = []
        seen_ids: set[str] = set()
        seen_body_keys: set[str] = set()
        for item in sorted(emergence_past, key=lambda x: x.turn_index, reverse=True):
            chunk_lines, chunk_ids = dedupe_memory_line_pairs(
                list(item.lines),
                list(item.unit_ids),
                seen_unit_ids=seen_ids,
                seen_body_keys=seen_body_keys,
            )
            for line, uid in zip(chunk_lines, chunk_ids):
                past_lines.append(line)
                past_ids.append(uid)
                if item.turn_index not in past_turns:
                    past_turns.append(item.turn_index)

        current_emergence_lines: list[str] = []
        current_emergence_ids: list[str] = []
        if emergence_current is not None:
            current_emergence_lines = list(emergence_current.lines)
            current_emergence_ids = list(emergence_current.unit_ids)
            self._take_turn_item(session_id, current_turn_index, "emergence")

        keyword_take = min(len(keyword_lines), math.ceil(ratio * budget))
        remaining = budget - keyword_take

        inject_lines: list[str] = []
        inject_ids: list[str] = []
        inject_seen_ids: set[str] = set()
        inject_seen_body_keys: set[str] = set()
        for line in past_lines:
            key = memory_line_body_key(line)
            if key:
                inject_seen_body_keys.add(key)
        sources: list[str] = []

        def _try_inject(line: str, uid: str, source: str) -> bool:
            if self._is_consumed(session_id, uid):
                return False
            added_lines, added_ids = dedupe_memory_line_pairs(
                [line],
                [uid],
                seen_unit_ids=inject_seen_ids,
                seen_body_keys=inject_seen_body_keys,
            )
            if not added_lines:
                return False
            inject_lines.append(added_lines[0])
            inject_ids.append(added_ids[0])
            if source not in sources:
                sources.append(source)
            return True

        social = self._social_prefetch.get(session_id)
        social_lines: list[str] = []
        social_ids: list[str] = []
        if social is not None:
            social_lines = list(social.lines)
            social_ids = list(social.unit_ids)

        warm = self.consume_warm_spread(session_id)
        warm_lines: list[str] = []
        warm_ids: list[str] = []
        if warm is not None:
            warm_lines = list(warm.lines)
            warm_ids = list(warm.unit_ids)

        for line, uid in zip(keyword_lines[:keyword_take], keyword_ids[:keyword_take]):
            if len(inject_lines) >= budget:
                break
            _try_inject(line, uid, "keyword")

        pool_lines = past_lines + current_emergence_lines
        pool_ids = past_ids + current_emergence_ids
        for line, uid in zip(pool_lines, pool_ids):
            if len(inject_lines) >= budget:
                break
            if self._is_consumed(session_id, uid):
                continue
            _try_inject(line, uid, "emergence")

        if len(inject_lines) < budget:
            for line, uid in zip(keyword_lines[keyword_take:], keyword_ids[keyword_take:]):
                if len(inject_lines) >= budget:
                    break
                _try_inject(line, uid, "keyword")

        spill_lines = [line for item in spilled for line in item.lines]
        spill_ids = [uid for item in spilled for uid in item.unit_ids]

        return MemoryComposePullResult(
            inject_lines=inject_lines[:budget],
            inject_unit_ids=inject_ids[:budget],
            inject_turn_indices=past_turns + ([current_turn_index] if keyword_item else []),
            social_prefetch_lines=social_lines,
            social_prefetch_unit_ids=social_ids,
            warm_spread_lines=warm_lines,
            warm_spread_unit_ids=warm_ids,
            merge_ratio=ratio,
            keyword_wait_ms=keyword_wait_ms,
            sources=sources,
            spilled_lines=spill_lines,
            spilled_unit_ids=spill_ids,
        )

    def peek_session(self, session_id: str) -> list[dict[str, object]]:
        queue = self._turn_queues.get(session_id, deque())
        out = [
            {
                "turn_index": item.turn_index,
                "lines": list(item.lines),
                "unit_ids": list(item.unit_ids),
                "source": item.source,
                "ready": item.ready,
            }
            for item in queue
        ]
        social = self._social_prefetch.get(session_id)
        if social is not None:
            out.append(
                {
                    "slot": "social_prefetch",
                    "turn_index": social.turn_index,
                    "lines": list(social.lines),
                    "unit_ids": list(social.unit_ids),
                    "source": social.source,
                }
            )
        warm = self._warm_spread.get(session_id)
        if warm is not None:
            out.append(
                {
                    "slot": "warm_spread",
                    "turn_index": warm.turn_index,
                    "lines": list(warm.lines),
                    "unit_ids": list(warm.unit_ids),
                    "source": warm.source,
                }
            )
        return out

    def clear_session(self, session_id: str) -> None:
        self._turn_queues.pop(session_id, None)
        self._social_prefetch.pop(session_id, None)
        self._warm_spread.pop(session_id, None)
        self._consumed_unit_ids.pop(session_id, None)
        self._recall_pick_multiplier.pop(session_id, None)
        with self._waiters_lock:
            cond = self._waiters.pop(session_id, None)
        if cond is not None:
            with cond:
                cond.notify_all()


SessionMemoryQueue = SessionMemoryBuffer
