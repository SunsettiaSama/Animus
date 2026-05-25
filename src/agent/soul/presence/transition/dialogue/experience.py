from __future__ import annotations

from dataclasses import dataclass

from agent.soul.presence.fsm.narrative import compose_narrative, normalize_narrative
from agent.soul.presence.fsm.state import PresenceState

from .block import DialogueBlock


@dataclass(frozen=True)
class DialogueExperience:
    """Presence 维护的连续对话体验（会话闭合时注入 memory）。"""

    perception: str
    narration: str
    emotion_label: str = ""
    block_count: int = 0


def render_dialogue_experience(
    state: PresenceState,
    blocks: list[DialogueBlock],
) -> DialogueExperience:
    perception = normalize_narrative(state.perception.narrative)
    if not perception and blocks:
        last = blocks[-1]
        cue = last.user_text.strip() or last.agent_text.strip()
        if cue:
            perception = f"我感知到：{cue}"

    narration = compose_narrative(
        normalize_narrative(state.cognition.thinking),
        normalize_narrative(state.affect.narrative),
    )
    if not narration and blocks:
        narration = f"与用户进行了 {len(blocks)} 轮对话。"

    emotion = normalize_narrative(state.affect.narrative)
    if emotion and len(emotion) <= 24:
        emotion_label = emotion
    else:
        emotion_label = ""

    return DialogueExperience(
        perception=perception,
        narration=narration,
        emotion_label=emotion_label,
        block_count=len(blocks),
    )
