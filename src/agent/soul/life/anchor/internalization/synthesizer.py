from __future__ import annotations

from agent.soul.life.experience.anchor_codec import (
    AnchorUnitContext,
    InteractionDirection,
    stamp_anchor_context,
)
from agent.soul.life.experience.sources import ExperienceSource
from agent.soul.life.experience.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)

from .session import InteractionSession


def _merge_memory_ids(session: InteractionSession) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for t in session.turns:
        for mid in t.activated_memory_ids:
            if mid and mid not in seen:
                seen.add(mid)
                out.append(mid)
    return out


def _pick_peak_turn(session: InteractionSession):
    return max(session.turns, key=lambda t: t.salience)


def _dialogue_block(session: InteractionSession) -> str:
    parts: list[str] = []
    if session.direction == InteractionDirection.outbound and session.outbound_message.strip():
        parts.append(f"我：{session.outbound_message.strip()}")
    for t in session.turns:
        if t.user_text.strip():
            parts.append(f"用户：{t.user_text.strip()}")
        if t.agent_reply.strip():
            parts.append(f"我：{t.agent_reply.strip()}")
    return "\n".join(parts)


def _narration_arc(session: InteractionSession) -> str:
    n = session.turn_count
    peak = _pick_peak_turn(session)
    if session.direction == InteractionDirection.outbound:
        head = "一次由我主动开口的相遇"
    else:
        head = "一次用户到来的对话"
    if n <= 1:
        return f"{head}，单轮来回，留下「{peak.emotion_label or '平静'}」的体感。"
    return (
        f"{head}，共 {n} 轮来回；"
        f"情绪以「{peak.emotion_label or '—'}」最为突出（显著度 {peak.salience:.2f}）。"
    )


def synthesize_interaction_unit(session: InteractionSession) -> ExperienceUnit:
    """将会话级相遇合成为一个 ExperienceUnit（source=interaction）。"""
    peak = _pick_peak_turn(session)
    last = session.turns[-1]
    n = session.turn_count
    salience = min(1.0, peak.salience + 0.05 * max(0, n - 1))

    unit = ExperienceUnit.make(
        situation=ExperienceSituation(
            session_id=session.session_id,
            turn_index=last.turn_index,
            perception=_dialogue_block(session),
            narration=_narration_arc(session),
            activated_memory_ids=_merge_memory_ids(session),
        ),
        action=ExperienceAction(
            kind=ExperienceActionKind.speaking,
            content=last.agent_reply or session.outbound_message,
        ),
        feeling=ExperienceFeeling(
            valence_delta=peak.valence_delta,
            arousal_delta=peak.arousal_delta,
            salience=salience,
            emotion_label=peak.emotion_label,
        ),
        source=ExperienceSource.interaction.value,
    )
    stamp_anchor_context(unit, AnchorUnitContext(
        direction=session.direction,
        session_id=session.session_id,
        proactive_intent_id=session.proactive_intent_id,
        interaction_id=session.id,
    ))
    return unit
