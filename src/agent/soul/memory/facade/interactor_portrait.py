from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InteractorPortraitSpeakResult:
    session_id: str
    turn_index: int
    interactor_id: str
    portrait_text: str
