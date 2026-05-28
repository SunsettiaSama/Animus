from __future__ import annotations

from dataclasses import dataclass, field

from ..anchor_codec import AnchorUnitContext, InteractionDirection, stamp_anchor_context
from ..sources import ExperienceSource
from ..unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from agent.soul.life.experience.dialogue.experience import DialogueExperience


@dataclass
class DialogueTurn:
    user_text: str
    agent_text: str
    salience: float = 0.3
    emotion_label: str = ""
    valence_delta: float = 0.0
    arousal_delta: float = 0.0
    activated_memory_ids: list[str] = field(default_factory=list)
    proactive_intent_id: str = ""


@dataclass
class DialogueSession:
    session_id: str
    direction: InteractionDirection = InteractionDirection.inbound
    outbound_message: str = ""
    proactive_intent_id: str = ""
    interactor_id: str = ""
    turns: list[DialogueTurn] = field(default_factory=list)


def render_session_transcript(session: DialogueSession) -> str:
    """全量对话 verbatim 串（memory 燃料，不做蒸馏）。"""
    parts: list[str] = []
    if session.direction == InteractionDirection.outbound and session.outbound_message.strip():
        parts.append(f"我：{session.outbound_message.strip()}")
    for turn in session.turns:
        if turn.user_text.strip():
            parts.append(f"用户：{turn.user_text.strip()}")
        if turn.agent_text.strip():
            parts.append(f"我：{turn.agent_text.strip()}")
    return "\n".join(parts)


def unit_from_dialogue_session(
    session: DialogueSession,
    experience: DialogueExperience,
) -> ExperienceUnit:
    peak = max(session.turns, key=lambda t: t.salience)
    last = session.turns[-1]
    n = len(session.turns)
    salience = min(1.0, peak.salience + 0.05 * max(0, n - 1))
    emotion_label = experience.emotion_label.strip() or peak.emotion_label
    transcript = render_session_transcript(session)

    memory_ids: list[str] = []
    seen: set[str] = set()
    for turn in session.turns:
        for mid in turn.activated_memory_ids:
            if mid and mid not in seen:
                seen.add(mid)
                memory_ids.append(mid)

    unit = ExperienceUnit.make(
        situation=ExperienceSituation(
            session_id=session.session_id,
            turn_index=n,
            perception=transcript,
            narration=experience.narration.strip() or experience.perception.strip(),
            activated_memory_ids=memory_ids,
        ),
        action=ExperienceAction(
            kind=ExperienceActionKind.speaking,
            content=last.agent_text or session.outbound_message,
        ),
        feeling=ExperienceFeeling(
            valence_delta=peak.valence_delta,
            arousal_delta=peak.arousal_delta,
            salience=salience,
            emotion_label=emotion_label,
        ),
        source=ExperienceSource.interaction.value,
    )
    stamp_anchor_context(unit, AnchorUnitContext(
        direction=session.direction,
        session_id=session.session_id,
        interactor_id=session.interactor_id.strip() or session.session_id,
        proactive_intent_id=session.proactive_intent_id,
    ))
    return unit
