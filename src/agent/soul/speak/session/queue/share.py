from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.presence.state.dynamic.expectation.queue import ShareIntent, ShareIntentQueue


@dataclass(frozen=True)
class ShareQueueItem:
    topic: str
    share_desire: ShareDesire = ShareDesire.mild
    source: str = ""
    salience: float = 0.0

    @classmethod
    def from_intent(cls, intent: ShareIntent) -> ShareQueueItem:
        return cls(
            topic=intent.topic,
            share_desire=intent.share_desire,
            source=intent.source,
            salience=intent.salience,
        )

    def to_intent(self) -> ShareIntent:
        return ShareIntent(
            topic=self.topic,
            share_desire=self.share_desire,
            source=self.source,
            salience=self.salience,
        )


class SessionShareQueue:
    """活跃会话内暂存的待分享话题（由 presence 延迟注入，最多保留少量）。"""

    def __init__(self, *, max_items: int = 8) -> None:
        self._max_items = max(1, max_items)
        self._queues: dict[str, deque[ShareQueueItem]] = {}
        self._consumption_history: dict[str, deque[dict[str, object]]] = {}

    def enqueue_batch(self, session_id: str, intents: list[ShareIntent]) -> int:
        if not intents:
            return 0
        queue = self._queues.setdefault(session_id, deque())
        added = 0
        for intent in intents:
            topic = intent.topic.strip()
            if not topic:
                continue
            queue.append(ShareQueueItem.from_intent(intent))
            added += 1
        while len(queue) > self._max_items:
            queue.popleft()
        return added

    def as_intent_queue(self, session_id: str) -> ShareIntentQueue:
        queue = self._queues.get(session_id)
        if not queue:
            return ShareIntentQueue()
        return ShareIntentQueue(items=[item.to_intent() for item in queue])

    def pop_most_wanted(self, session_id: str) -> ShareIntent | None:
        queue = self._queues.get(session_id)
        if not queue:
            return None
        best_index = max(range(len(queue)), key=lambda i: queue[i].salience)
        item = queue[best_index]
        del queue[best_index]
        if not queue:
            self._queues.pop(session_id, None)
        return item.to_intent()

    def pop_at(self, session_id: str, index: int) -> ShareIntent | None:
        queue = self._queues.get(session_id)
        if not queue or index < 0 or index >= len(queue):
            return None
        item = queue[index]
        del queue[index]
        if not queue:
            self._queues.pop(session_id, None)
        return item.to_intent()

    def pop_by_topic(self, session_id: str, topic: str) -> ShareIntent | None:
        """按话题正文精确匹配弹出（角色消费分享卡片用）。"""
        text = topic.strip()
        if not text:
            return None
        queue = self._queues.get(session_id)
        if not queue:
            return None
        for index, item in enumerate(queue):
            if item.topic.strip() == text:
                return self.pop_at(session_id, index)
        return None

    def consume_at(
        self,
        session_id: str,
        index: int,
        *,
        turn_index: int = 0,
        trigger_id: str = "",
    ) -> ShareIntent | None:
        item = self.pop_at(session_id, index)
        if item is not None:
            self._record_consumption(
                session_id,
                item,
                turn_index=turn_index,
                trigger_id=trigger_id,
            )
        return item

    def consume_by_topic(
        self,
        session_id: str,
        topic: str,
        *,
        turn_index: int = 0,
        trigger_id: str = "",
    ) -> ShareIntent | None:
        item = self.pop_by_topic(session_id, topic)
        if item is not None:
            self._record_consumption(
                session_id,
                item,
                turn_index=turn_index,
                trigger_id=trigger_id,
            )
        return item

    def _record_consumption(
        self,
        session_id: str,
        item: ShareIntent,
        *,
        turn_index: int,
        trigger_id: str,
    ) -> None:
        history = self._consumption_history.setdefault(session_id, deque(maxlen=12))
        history.append(
            {
                "topic": item.topic,
                "source": item.source,
                "turn_index": int(turn_index or 0),
                "trigger_id": trigger_id.strip(),
                "consumed_at": time.time(),
            }
        )

    def peek_session(self, session_id: str) -> list[dict[str, object]]:
        queue = self._queues.get(session_id)
        if not queue:
            return []
        return [
            {
                "topic": item.topic,
                "share_desire": item.share_desire.value,
                "source": item.source,
                "salience": item.salience,
            }
            for item in queue
        ]

    def consumption_history(self, session_id: str) -> list[dict[str, object]]:
        return [dict(item) for item in self._consumption_history.get(session_id, ())]

    def clear_session(self, session_id: str) -> None:
        self._queues.pop(session_id, None)
        self._consumption_history.pop(session_id, None)
