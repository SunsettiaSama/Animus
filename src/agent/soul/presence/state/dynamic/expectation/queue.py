from __future__ import annotations

from dataclasses import dataclass, field

from config.soul.presence.config import SHARE_INTENT_QUEUE_MAX_ITEMS
from agent.soul.presence.share_desire import ShareDesire, max_share_desire


@dataclass(frozen=True)
class ShareIntent:
    """Agent 想分享给用户的一条话题。"""

    topic: str
    share_desire: ShareDesire = ShareDesire.mild
    source: str = ""
    salience: float = 0.0

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "share_desire": self.share_desire.value,
            "source": self.source,
            "salience": round(self.salience, 4),
        }

    @classmethod
    def from_dict(cls, d: dict) -> ShareIntent:
        return cls(
            topic=str(d.get("topic", "")),
            share_desire=ShareDesire(str(d.get("share_desire", ShareDesire.mild.value))),
            source=str(d.get("source", "")),
            salience=float(d.get("salience", 0.0)),
        )


@dataclass
class ShareIntentQueue:
    """待分享话题队列（持久化于 ExpectationState）。"""

    items: list[ShareIntent] = field(default_factory=list)
    _max_items: int = SHARE_INTENT_QUEUE_MAX_ITEMS

    def enqueue(self, intent: ShareIntent) -> None:
        topic = intent.topic.strip()
        if not topic:
            return
        normalized = ShareIntent(
            topic=topic,
            share_desire=intent.share_desire,
            source=intent.source,
            salience=intent.salience,
        )
        self.items.append(normalized)
        if len(self.items) > self._max_items:
            self.items = self.items[-self._max_items :]

    def drain(self) -> list[ShareIntent]:
        drained = list(self.items)
        self.items.clear()
        return drained

    def peek(self) -> ShareIntent | None:
        if not self.items:
            return None
        return self.items[0]

    def fold_summary(self) -> str:
        if not self.items:
            return ""
        ordered = sorted(self.items, key=lambda item: item.salience, reverse=True)
        primary = ordered[0]
        if len(self.items) == 1:
            return primary.topic
        return f"{primary.topic}（另有 {len(self.items) - 1} 条想分享的事）"

    def peak_share_desire(self) -> ShareDesire:
        peak = ShareDesire.none
        for item in self.items:
            peak = max_share_desire(peak, item.share_desire)
        return peak

    def pop_most_wanted(self) -> ShareIntent | None:
        """弹出当前最想分享的一条（按 salience 最高）。"""
        if not self.items:
            return None
        best_index = max(range(len(self.items)), key=lambda i: self.items[i].salience)
        return self.items.pop(best_index)

    def is_empty(self) -> bool:
        return not self.items

    def __len__(self) -> int:
        return len(self.items)

    def copy(self) -> ShareIntentQueue:
        return ShareIntentQueue(items=[ShareIntent.from_dict(i.to_dict()) for i in self.items])

    def to_dict(self) -> dict:
        return {"items": [item.to_dict() for item in self.items]}

    @classmethod
    def from_dict(cls, d: dict | None) -> ShareIntentQueue:
        if not d:
            return cls()
        return cls(items=[ShareIntent.from_dict(item) for item in d.get("items", [])])
