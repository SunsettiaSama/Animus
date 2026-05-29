from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DialogueContextChunk:
    user_text: str
    agent_text: str
