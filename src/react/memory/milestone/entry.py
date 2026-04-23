from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class MilestoneEntry:
    id: str
    summary: str
    detail: str
    created_at: str
    keywords: list[str]
    emotion: str          # "positive" | "negative" | "neutral"
    importance: float

    @staticmethod
    def new(
        summary: str,
        detail: str,
        keywords: list[str],
        emotion: str = "neutral",
        importance: float = 0.7,
    ) -> MilestoneEntry:
        return MilestoneEntry(
            id=str(uuid.uuid4()),
            summary=summary,
            detail=detail,
            created_at=datetime.now(timezone.utc).isoformat(),
            keywords=keywords,
            emotion=emotion,
            importance=importance,
        )
