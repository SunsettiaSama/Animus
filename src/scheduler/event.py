from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class TimelineEvent:
    type: str
    ts: str
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def now(cls, type: str, payload: dict[str, Any] | None = None) -> TimelineEvent:
        return cls(
            type=type,
            ts=datetime.now(timezone.utc).isoformat(),
            payload=payload or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "ts": self.ts, "payload": self.payload}
