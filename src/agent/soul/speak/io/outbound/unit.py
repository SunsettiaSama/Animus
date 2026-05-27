from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


@dataclass
class SpeakAnswer:
    """Agent 对外最小话语单元。"""

    text: str
    id: str = field(default_factory=_uid)
    at: str = field(default_factory=_now_iso)
    final: bool = False
