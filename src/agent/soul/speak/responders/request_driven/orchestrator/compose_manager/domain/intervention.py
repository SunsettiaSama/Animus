from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

DirectorMemoryAction = Literal["inject", "remove", "none"]


@dataclass(frozen=True)
class DirectorMemoryIntervention:
    action: DirectorMemoryAction = "none"
    unit_id: str = ""
    text: str = ""
    reason: str = ""
