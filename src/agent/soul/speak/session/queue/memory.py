from __future__ import annotations

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

    def enqueue(self, session_id: str, item: MemoryQueueItem) -> None:
        prior = self._queues.get(session_id, deque())
        queue = deque(existing for existing in prior if existing.turn_index != item.turn_index)
        queue.append(item)
        self._queues[session_id] = queue

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

    def clear_session(self, session_id: str) -> None:
        self._queues.pop(session_id, None)
