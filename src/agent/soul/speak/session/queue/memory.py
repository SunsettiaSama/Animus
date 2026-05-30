from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class MemoryQueueItem:
    turn_index: int
    lines: tuple[str, ...]
    unit_ids: tuple[str, ...]
    associative_ready: bool = False


@dataclass
class MemoryQueueConsumeResult:
    inject_lines: list[str] = field(default_factory=list)
    inject_unit_ids: list[str] = field(default_factory=list)
    inject_turn_index: int = 0
    spilled_lines: list[str] = field(default_factory=list)
    spilled_unit_ids: list[str] = field(default_factory=list)
    spilled_turn_index: int = 0


class SessionMemoryQueue:
    """按 turn_index 缓存相似记忆；compose 时按轮次邻近规则注入或抛出。"""

    def __init__(self, *, max_turn_gap: int = 3) -> None:
        self._max_turn_gap = max(1, max_turn_gap)
        self._queues: dict[str, deque[MemoryQueueItem]] = {}
        self._waiters: dict[str, threading.Condition] = {}
        self._waiters_lock = threading.Lock()

    def _condition(self, session_id: str) -> threading.Condition:
        with self._waiters_lock:
            cond = self._waiters.get(session_id)
            if cond is None:
                cond = threading.Condition()
                self._waiters[session_id] = cond
            return cond

    def enqueue(self, session_id: str, item: MemoryQueueItem) -> None:
        prior = self._queues.get(session_id, deque())
        queue = deque(existing for existing in prior if existing.turn_index != item.turn_index)
        queue.append(item)
        self._queues[session_id] = queue
        with self._condition(session_id):
            self._condition(session_id).notify_all()

    def has_turn(self, session_id: str, turn_index: int) -> bool:
        queue = self._queues.get(session_id)
        if not queue:
            return False
        return any(item.turn_index == turn_index for item in queue)

    def wait_for_turn(
        self,
        session_id: str,
        turn_index: int,
        timeout_ms: int,
    ) -> bool:
        if timeout_ms <= 0:
            return self.has_turn(session_id, turn_index)
        deadline = time.monotonic() + timeout_ms / 1000.0
        cond = self._condition(session_id)
        with cond:
            while not self.has_turn(session_id, turn_index):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                cond.wait(timeout=remaining)
            return True

    def consume_turn_exact(
        self,
        session_id: str,
        turn_index: int,
    ) -> MemoryQueueConsumeResult:
        queue = self._queues.get(session_id)
        if not queue:
            return MemoryQueueConsumeResult()

        kept: deque[MemoryQueueItem] = deque()
        found: MemoryQueueItem | None = None
        for item in queue:
            if item.turn_index == turn_index and found is None:
                found = item
            else:
                kept.append(item)
        self._queues[session_id] = kept

        if found is None:
            return MemoryQueueConsumeResult()
        return MemoryQueueConsumeResult(
            inject_lines=list(found.lines),
            inject_unit_ids=list(found.unit_ids),
            inject_turn_index=found.turn_index,
        )

    def consume_for_compose(self, session_id: str, current_turn_index: int) -> MemoryQueueConsumeResult:
        queue = self._queues.get(session_id)
        if not queue:
            return MemoryQueueConsumeResult()

        inject_lines: list[str] = []
        inject_unit_ids: list[str] = []
        inject_turn_index = 0
        spilled_lines: list[str] = []
        spilled_unit_ids: list[str] = []
        spilled_turn_index = 0

        while queue:
            head = queue[0]
            gap = abs(head.turn_index - current_turn_index)
            if gap < self._max_turn_gap:
                item = queue.popleft()
                inject_lines.extend(item.lines)
                inject_unit_ids.extend(item.unit_ids)
                if not inject_turn_index:
                    inject_turn_index = item.turn_index
                continue
            while queue and abs(queue[0].turn_index - current_turn_index) >= self._max_turn_gap:
                stale = queue.popleft()
                spilled_lines.extend(stale.lines)
                spilled_unit_ids.extend(stale.unit_ids)
                if not spilled_turn_index:
                    spilled_turn_index = stale.turn_index

        return MemoryQueueConsumeResult(
            inject_lines=inject_lines,
            inject_unit_ids=inject_unit_ids,
            inject_turn_index=inject_turn_index,
            spilled_lines=spilled_lines,
            spilled_unit_ids=spilled_unit_ids,
            spilled_turn_index=spilled_turn_index,
        )

    def pull_for_compose(
        self,
        session_id: str,
        current_turn_index: int,
        *,
        wait_ms: int = 0,
    ) -> MemoryQueueConsumeResult:
        """等待当前轮异步结果（最多 wait_ms）；超时则消费上一轮库存。"""
        if wait_ms > 0:
            self.wait_for_turn(session_id, current_turn_index, wait_ms)
        if self.has_turn(session_id, current_turn_index):
            return self.consume_turn_exact(session_id, current_turn_index)
        return self.consume_for_compose(session_id, current_turn_index)

    def peek_session(self, session_id: str) -> list[dict[str, object]]:
        queue = self._queues.get(session_id)
        if not queue:
            return []
        return [
            {
                "turn_index": item.turn_index,
                "lines": list(item.lines),
                "unit_ids": list(item.unit_ids),
                "associative_ready": item.associative_ready,
            }
            for item in queue
        ]

    def clear_session(self, session_id: str) -> None:
        self._queues.pop(session_id, None)
        with self._waiters_lock:
            cond = self._waiters.pop(session_id, None)
        if cond is not None:
            with cond:
                cond.notify_all()
