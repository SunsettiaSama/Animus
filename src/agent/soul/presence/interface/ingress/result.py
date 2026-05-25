from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ...transition import PresenceTransitionOutcome, PresenceTrigger
from ..egress.request import SpeakRequest

if TYPE_CHECKING:
    from ...service import PresenceSnapshot


@dataclass
class PresenceTriggerResult:
    """ingress trigger 入站结果（可携带 egress SpeakRequest）。"""

    outcome: PresenceTransitionOutcome
    before: PresenceSnapshot | None = None
    after: PresenceSnapshot | None = None
    speak_request: SpeakRequest | None = None
    boundary: bool = False
    buffered_share_count: int = 0

    @property
    def trigger(self) -> PresenceTrigger:
        return self.outcome.trigger

    @property
    def applied(self) -> bool:
        return self.outcome.applied

    @property
    def notes(self) -> list[str]:
        return self.outcome.notes

    @property
    def outbound_request(self) -> SpeakRequest | None:
        return self.speak_request
