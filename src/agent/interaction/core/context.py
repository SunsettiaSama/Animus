from __future__ import annotations

from dataclasses import dataclass, field

from .expectation import Expectation


@dataclass
class SceneRef:
    """交织场引用（叙事包装由情景 LLM 填充；门控行为权）。"""

    scene_id: str
    kind: str = ""
    title: str = ""
    frame_text: str = ""


@dataclass
class InteractionContext:
    """单次 SemanticInteraction 的背景场（非单元本身）。"""

    session_id: str
    channel: str = ""
    expectation: Expectation = Expectation.required
    in_scene: bool = False
    active_scene: SceneRef | None = None
    proactive_intent_id: str = ""
    meta: dict = field(default_factory=dict)
