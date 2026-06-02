from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InteractorPortraitSpeakResult:
    session_id: str
    turn_index: int
    interactor_id: str
    portrait_text: str
    display_name: str = ""
    core_traits: tuple[str, ...] = ()
    portrait_body: str = ""
    agent_relation: str = ""
    recent_impression: str = ""
    neighborhood_snippets: tuple[str, ...] = ()
