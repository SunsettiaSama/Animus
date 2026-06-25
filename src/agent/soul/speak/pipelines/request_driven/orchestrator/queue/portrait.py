from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass(frozen=True)
class PortraitQueueItem:
    turn_index: int
    interactor_id: str
    portrait_text: str


@dataclass
class PortraitQueueConsumeResult:
    portrait_text: str = ""
    interactor_id: str = ""
    inject_turn_index: int = 0
    spilled_text: str = ""
    spilled_interactor_id: str = ""
    spilled_turn_index: int = 0


class ComposePortraitQueue:
    """按 turn_index 缓存异步解析的对话者画像；compose 时按邻近规则注入。"""

    def __init__(self, *, max_turn_gap: int = 3) -> None:
        self._max_turn_gap = max(1, max_turn_gap)
        self._queues: dict[str, deque[PortraitQueueItem]] = {}
        self._waiters: dict[str, threading.Condition] = {}
        self._waiters_lock = threading.Lock()

    def _condition(self, session_id: str) -> threading.Condition:
        with self._waiters_lock:
            cond = self._waiters.get(session_id)
            if cond is None:
                cond = threading.Condition()
                self._waiters[session_id] = cond
            return cond

    def enqueue(self, session_id: str, item: PortraitQueueItem) -> None:
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
    ) -> PortraitQueueConsumeResult:
        queue = self._queues.get(session_id)
        if not queue:
            return PortraitQueueConsumeResult()

        kept: deque[PortraitQueueItem] = deque()
        found: PortraitQueueItem | None = None
        for item in queue:
            if item.turn_index == turn_index and found is None:
                found = item
            else:
                kept.append(item)
        self._queues[session_id] = kept

        if found is None or not found.portrait_text.strip():
            return PortraitQueueConsumeResult()
        return PortraitQueueConsumeResult(
            portrait_text=found.portrait_text.strip(),
            interactor_id=found.interactor_id.strip(),
            inject_turn_index=found.turn_index,
        )

    def consume_for_compose(
        self,
        session_id: str,
        current_turn_index: int,
    ) -> PortraitQueueConsumeResult:
        queue = self._queues.get(session_id)
        if not queue:
            return PortraitQueueConsumeResult()

        inject_text = ""
        inject_interactor_id = ""
        inject_turn_index = 0
        spilled_text = ""
        spilled_interactor_id = ""
        spilled_turn_index = 0

        while queue:
            head = queue[0]
            gap = abs(head.turn_index - current_turn_index)
            if gap < self._max_turn_gap:
                item = queue.popleft()
                if item.portrait_text.strip():
                    inject_text = item.portrait_text.strip()
                    inject_interactor_id = item.interactor_id.strip()
                    inject_turn_index = item.turn_index
                continue
            while queue and abs(queue[0].turn_index - current_turn_index) >= self._max_turn_gap:
                stale = queue.popleft()
                if stale.portrait_text.strip():
                    spilled_text = stale.portrait_text.strip()
                    spilled_interactor_id = stale.interactor_id.strip()
                    spilled_turn_index = stale.turn_index

        return PortraitQueueConsumeResult(
            portrait_text=inject_text,
            interactor_id=inject_interactor_id,
            inject_turn_index=inject_turn_index,
            spilled_text=spilled_text,
            spilled_interactor_id=spilled_interactor_id,
            spilled_turn_index=spilled_turn_index,
        )

    def pull_for_compose(
        self,
        session_id: str,
        current_turn_index: int,
        *,
        wait_ms: int = 0,
    ) -> PortraitQueueConsumeResult:
        if wait_ms > 0:
            self.wait_for_turn(session_id, current_turn_index, wait_ms)
        if self.has_turn(session_id, current_turn_index):
            exact = self.consume_turn_exact(session_id, current_turn_index)
            if exact.portrait_text.strip():
                return exact
        return self.consume_for_compose(session_id, current_turn_index)

    def peek_session(self, session_id: str) -> list[dict[str, object]]:
        queue = self._queues.get(session_id)
        if not queue:
            return []
        return [
            {
                "turn_index": item.turn_index,
                "interactor_id": item.interactor_id,
                "portrait_chars": len(item.portrait_text),
                "portrait_preview": item.portrait_text[:200],
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
