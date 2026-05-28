from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class InteractorRef:
    id: str
    display_name: str = ""
    created_at: datetime = field(default_factory=_now)
