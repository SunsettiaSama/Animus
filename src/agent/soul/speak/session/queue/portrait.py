from __future__ import annotations

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


class SessionPortraitQueue:
    """按 turn_index 缓存异步解析的对话者画像；compose 时按邻近规则注入。"""

    def __init__(self, *, max_turn_gap: int = 3) -> None:
        self._max_turn_gap = max(1, max_turn_gap)
        self._queues: dict[str, deque[PortraitQueueItem]] = {}

    def enqueue(self, session_id: str, item: PortraitQueueItem) -> None:
        prior = self._queues.get(session_id, deque())
        queue = deque(existing for existing in prior if existing.turn_index != item.turn_index)
        queue.append(item)
        self._queues[session_id] = queue

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

    def clear_session(self, session_id: str) -> None:
        self._queues.pop(session_id, None)
