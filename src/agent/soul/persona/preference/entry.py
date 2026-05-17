from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class PreferenceEntry:
    """单次偏好快照，携带写入时间戳。

    每轮（或每 N 轮）对话结束后由 LLM 分析生成，追加到 RecentPreference 的滑动窗口中。
    """

    id: str
    recorded_at: str                          # ISO 8601 UTC
    mood: str = "neutral"
    topic_interests: list[str] = field(default_factory=list)
    style_shifts: dict[str, float] = field(default_factory=dict)

    @staticmethod
    def new(
        mood: str = "neutral",
        topic_interests: list[str] | None = None,
        style_shifts: dict[str, float] | None = None,
    ) -> PreferenceEntry:
        return PreferenceEntry(
            id=str(uuid.uuid4()),
            recorded_at=datetime.now(timezone.utc).isoformat(),
            mood=mood,
            topic_interests=topic_interests or [],
            style_shifts=style_shifts or {},
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "recorded_at": self.recorded_at,
            "mood": self.mood,
            "topic_interests": self.topic_interests,
            "style_shifts": self.style_shifts,
        }

    @staticmethod
    def from_dict(d: dict) -> PreferenceEntry:
        return PreferenceEntry(
            id=d.get("id", str(uuid.uuid4())),
            recorded_at=d.get("recorded_at", ""),
            mood=d.get("mood", "neutral"),
            topic_interests=list(d.get("topic_interests", [])),
            style_shifts={str(k): float(v) for k, v in d.get("style_shifts", {}).items()},
        )
