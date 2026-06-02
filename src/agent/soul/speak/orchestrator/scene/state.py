from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .layer import SpeakSceneLayer


@dataclass(frozen=True)
class SceneUpdateResult:
    ok: bool
    scene_id: str | None = None
    scene_name: str = ""
    inject_text: str = ""
    transition_text: str = ""
    matched_by: str = ""
    resolve_method: str = ""
    candidates_count: int = 0
    query: str = ""
    locate: Any = None


@dataclass
class SceneComposeState:
    version: int
    result: SceneUpdateResult
    layer: SpeakSceneLayer
    meta: dict[str, Any] = field(default_factory=dict)
