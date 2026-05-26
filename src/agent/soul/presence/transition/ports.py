from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..state import PresenceState
from .interaction import PresenceInteraction


@dataclass
class TransitionNotes:
    applied: bool = True
    notes: list[str] = field(default_factory=list)


class TransitionHandler(Protocol):
    def apply(
        self,
        *,
        session_id: str,
        state: PresenceState,
        interaction: PresenceInteraction,
        payload: object,
    ) -> TransitionNotes: ...
