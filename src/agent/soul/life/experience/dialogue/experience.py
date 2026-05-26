from __future__ import annotations

from dataclasses import dataclass

from agent.soul.presence.state.static import compose_narrative, normalize_narrative
from agent.soul.presence.state import PresenceState


@dataclass(frozen=True)
class DialogueExperience:
    """连续对话体验（会话闭合时注入 memory）。"""

    perception: str
    narration: str
    emotion_label: str = ""
    block_count: int = 0


def build_dialogue_experience(
    state: PresenceState,
    *,
    block_count: int = 0,
) -> DialogueExperience:
    perception = normalize_narrative(state.perception.narrative)
    narration = compose_narrative(
        normalize_narrative(state.cognition.thinking),
        normalize_narrative(state.affect.narrative),
    )
    if not narration:
        narration = "与用户进行了对话。"

    emotion = normalize_narrative(state.affect.narrative)
    emotion_label = emotion if emotion and len(emotion) <= 24 else ""

    return DialogueExperience(
        perception=perception,
        narration=narration,
        emotion_label=emotion_label,
        block_count=block_count,
    )
