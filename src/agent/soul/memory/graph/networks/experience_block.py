from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .types import ExperienceBlock, ExperienceKind

if TYPE_CHECKING:
    from agent.soul.life.experience.domain.unit import ExperienceUnit

_ANCHOR_CTX_PREFIX = "__actx:"
_REALITY_SOURCES = frozenset({"user", "interaction"})


@dataclass(frozen=True)
class _AnchorContext:
    session_id: str = "tao"
    interactor_id: str = ""


def _read_anchor_context(unit: ExperienceUnit) -> _AnchorContext | None:
    raw = (unit.situation.prior_thought or "").strip()
    if not raw.startswith(_ANCHOR_CTX_PREFIX):
        return None
    payload = json.loads(raw[len(_ANCHOR_CTX_PREFIX):])
    return _AnchorContext(
        session_id=str(payload.get("session_id", "tao")),
        interactor_id=str(payload.get("interactor_id", "")),
    )


def classify_experience(unit: ExperienceUnit) -> ExperienceKind:
    if _read_anchor_context(unit) is not None:
        return ExperienceKind.anchor
    if unit.source in _REALITY_SOURCES:
        return ExperienceKind.anchor
    return ExperienceKind.event


def resolve_interactor_id(unit: ExperienceUnit) -> str:
    ctx = _read_anchor_context(unit)
    if ctx is not None:
        interactor = (ctx.interactor_id or "").strip()
        if interactor:
            return interactor
        if classify_experience(unit) == ExperienceKind.anchor:
            session_id = (ctx.session_id or "").strip()
            if session_id:
                return session_id
    return ""


def experience_raw_text(unit: ExperienceUnit) -> str:
    parts = [
        unit.situation.perception,
        unit.situation.narration,
        unit.action.content,
    ]
    return " ".join(p.strip() for p in parts if p and p.strip())


def read_experience_block(unit: ExperienceUnit) -> ExperienceBlock:
    kind = classify_experience(unit)
    interactor_id = resolve_interactor_id(unit)
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
