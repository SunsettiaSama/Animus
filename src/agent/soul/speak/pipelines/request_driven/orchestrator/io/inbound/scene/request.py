from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SceneUpdateRequest:
    session_id: str
    query: str
    turn_index: int = 0
    world_id: str = ""
    force: bool = False
