from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .enums import EdgeType


def _uid() -> str:
    return str(uuid.uuid4())


@dataclass
class MemoryEdge:
    from_id: str
    to_id: str
    edge_type: EdgeType
    weight: float = 1.0
    meta: dict = field(default_factory=dict)
    id: str = field(default_factory=_uid)
