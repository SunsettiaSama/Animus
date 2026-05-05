from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plan.document import PlanDocument


@dataclass
class PlanResult:
    plan_id: str
    status: str                          # done | aborted | failed
    answer: str = ""
    error: str = ""
    doc: PlanDocument | None = field(default=None)
