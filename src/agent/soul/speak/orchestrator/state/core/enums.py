from __future__ import annotations

from typing import Literal

Continuity = Literal["append", "finish"]
KNOWN_CONTINUITY: frozenset[str] = frozenset({"append", "finish"})

SpeakGateAction = Literal["listen", "speak", "hold", "brew"]
KNOWN_SPEAK_GATE: frozenset[str] = frozenset({"listen", "speak", "hold", "brew"})

DialogueRhythm = Literal["opening", "exchange", "deepening", "closing", "idle"]
KNOWN_RHYTHM: frozenset[str] = frozenset(
    {"opening", "exchange", "deepening", "closing", "idle"},
)


def normalize_continuity(value: str) -> Continuity:
    normalized = str(value or "").strip().lower()
    if normalized in KNOWN_CONTINUITY:
        return normalized  # type: ignore[return-value]
    return "finish"


def normalize_rhythm(value: str) -> DialogueRhythm:
    normalized = str(value or "").strip().lower()
    if normalized in KNOWN_RHYTHM:
        return normalized  # type: ignore[return-value]
    return "exchange"
