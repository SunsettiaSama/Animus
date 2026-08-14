from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from ..blocks.system.role import SpeakTurnMode


@dataclass(frozen=True)
class ComposeQueueItem:
    session_id: str
    mode: SpeakTurnMode
    frame: Any


@dataclass
class ComposeFrameQueue:
    """compose 就绪帧队列：后台预组装完成后供下一轮消费。"""

    _queues: dict[tuple[str, str], deque[ComposeQueueItem]] = field(default_factory=dict)

    def enqueue(self, frame, *, mode: SpeakTurnMode = "inbound") -> ComposeQueueItem:
        item = ComposeQueueItem(session_id=frame.session_id, mode=mode, frame=frame)
        key = (frame.session_id, mode)
        if key not in self._queues:
            self._queues[key] = deque()
        self._queues[key].append(item)
        return item

    def pop(self, session_id: str, *, mode: SpeakTurnMode = "inbound") -> ComposeQueueItem | None:
        key = (session_id, mode)
        queue = self._queues.get(key)
        if queue is None or not queue:
            return None
        return queue.popleft()

    def peek(self, session_id: str, *, mode: SpeakTurnMode = "inbound") -> ComposeQueueItem | None:
        key = (session_id, mode)
        queue = self._queues.get(key)
        if queue is None or not queue:
            return None
        return queue[0]

    def has_pending(self, session_id: str, *, mode: SpeakTurnMode = "inbound") -> bool:
        return self.peek(session_id, mode=mode) is not None

    def clear_session(self, session_id: str) -> None:
        keys = [key for key in self._queues if key[0] == session_id]
        for key in keys:
            del self._queues[key]

    def size(self, session_id: str, *, mode: SpeakTurnMode = "inbound") -> int:
        key = (session_id, mode)
        queue = self._queues.get(key)
        if queue is None:
            return 0
        return len(queue)
