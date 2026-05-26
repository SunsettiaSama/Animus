from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .discharge import ImpulseDischarge
from .transition import PresenceTransitionOutcome, PresenceTrigger

if TYPE_CHECKING:
    from .service import PresenceSnapshot


@dataclass
class GatewayResult:
    """Gateway 入站结果（仅状态转移，不携带出站 speak）。"""

    outcome: PresenceTransitionOutcome
    before: PresenceSnapshot | None = None
    after: PresenceSnapshot | None = None
    boundary: bool = False
    buffered_share_count: int = 0
    impulse_discharge: ImpulseDischarge | None = None

    @property
    def trigger(self) -> PresenceTrigger:
        return self.outcome.trigger

    @property
    def applied(self) -> bool:
        return self.outcome.applied

    @property
    def notes(self) -> list[str]:
        return self.outcome.notes


PresenceTriggerResult = GatewayResult
