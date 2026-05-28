from __future__ import annotations

from agent.soul.life.experience.anchor_codec import read_anchor_context
from agent.soul.life.experience.sources import REALITY_SOURCES
from agent.soul.life.experience.unit import ExperienceUnit

from .types import ExperienceBlock, ExperienceKind


def classify_experience(unit: ExperienceUnit) -> ExperienceKind:
    if read_anchor_context(unit) is not None:
        return ExperienceKind.anchor
    if unit.source in REALITY_SOURCES:
        return ExperienceKind.anchor
    return ExperienceKind.event


def resolve_interactor_id(unit: ExperienceUnit) -> str:
    ctx = read_anchor_context(unit)
    if ctx is not None:
        interactor = (ctx.interactor_id or "").strip()
        if interactor:
            return interactor
        session_id = (ctx.session_id or "").strip()
        if session_id:
            return session_id
    session_id = (unit.situation.session_id or "").strip()
    if session_id:
        return session_id
    return unit.id[:8]


def experience_raw_text(unit: ExperienceUnit) -> str:
    parts = [
        unit.situation.perception,
        unit.situation.narration,
        unit.action.content,
    ]
    return " ".join(p.strip() for p in parts if p and p.strip())


def read_experience_block(unit: ExperienceUnit) -> ExperienceBlock:
    kind = classify_experience(unit)
    interactor_id = resolve_interactor_id(unit) if kind == ExperienceKind.anchor else ""
    raw = experience_raw_text(unit)
    if not raw:
        raw = unit.id[:8]
    return ExperienceBlock(
        experience_id=unit.id,
        source=unit.source,
        kind=kind,
        interactor_id=interactor_id,
        raw_text=raw,
        emotion_label=unit.feeling.emotion_label,
        salience=unit.feeling.salience,
        valence_delta=unit.feeling.valence_delta,
    )
