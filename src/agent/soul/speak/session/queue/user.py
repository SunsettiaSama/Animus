from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .types import SpeakTurnMode


@dataclass(frozen=True)
class UserInputItem:
    session_id: str
    user_text: str
    mode: SpeakTurnMode = "inbound"
    stream: bool = False
    record: bool = True
    interrupted: bool = False


@dataclass
class SessionUserQueue:
    """用户输入队列：插队时插入队首（最新优先）。"""

    _queues: dict[str, deque[UserInputItem]] = field(default_factory=dict)

    def push_front(self, item: UserInputItem) -> None:
        queue = self._queues.setdefault(item.session_id, deque())
        queue.appendleft(item)

    def push_back(self, item: UserInputItem) -> None:
        queue = self._queues.setdefault(item.session_id, deque())
        queue.append(item)

    def pop(self, session_id: str) -> UserInputItem | None:
        queue = self._queues.get(session_id)
        if queue is None or not queue:
            return None
        return queue.popleft()

    def peek(self, session_id: str) -> UserInputItem | None:
        queue = self._queues.get(session_id)
        if queue is None or not queue:
            return None
        return queue[0]

    def has_pending(self, session_id: str) -> bool:
        return self.peek(session_id) is not None

    def clear_session(self, session_id: str) -> None:
        self._queues.pop(session_id, None)

    def size(self, session_id: str) -> int:
        queue = self._queues.get(session_id)
        if queue is None:
            return 0
        return len(queue)
