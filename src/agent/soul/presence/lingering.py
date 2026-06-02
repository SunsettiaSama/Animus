from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.soul.life.anchor.presence_bundle import PresenceExperienceBundle
from agent.soul.life.experience.domain.unit import ExperienceUnit

from .state import PresenceState
from .state.lingering import LingeringMood

from config.soul.presence.config import (
    LINGER_DAYS_DEFAULT,
    LINGER_DAYS_HIGH_SALIENCE,
    LINGER_SALIENCE_HIGH_THRESHOLD,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_after_days(days: float) -> str:
    return (_now_utc() + timedelta(days=max(0.25, days))).isoformat()


def resolve_linger_days(
    unit: ExperienceUnit,
    *,
    default_days: float = LINGER_DAYS_DEFAULT,
    high_days: float = LINGER_DAYS_HIGH_SALIENCE,
    high_threshold: float = LINGER_SALIENCE_HIGH_THRESHOLD,
) -> float:
    explicit = float(unit.feeling.linger_days or 0.0)
    if explicit > 0.0:
        return explicit
    salience = float(unit.feeling.salience or 0.0)
    if salience >= high_threshold:
        return high_days
    if salience >= 0.45:
        return max(default_days, 3.0)
    return default_days


def expire_lingering_moods(state: PresenceState, *, now: datetime | None = None) -> None:
    now = now or _now_utc()
    kept: list[LingeringMood] = []
    for mood in state.lingering_moods:
        until_raw = mood.until_iso.strip()
        if not until_raw:
            continue
        until = datetime.fromisoformat(until_raw.replace("Z", "+00:00"))
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        if until > now:
            kept.append(mood)
    state.lingering_moods = kept


def _upsert_lingering(
    state: PresenceState,
    text: str,
    *,
    days: float,
    source_unit_id: str,
) -> None:
    text = text.strip()
    if not text:
        return
    until_iso = _iso_after_days(days)
    for mood in state.lingering_moods:
        if mood.text == text:
            mood.until_iso = until_iso
            mood.source_unit_id = source_unit_id
            return
    state.lingering_moods.append(
        LingeringMood(text=text, until_iso=until_iso, source_unit_id=source_unit_id),
    )


def apply_unit_lingering(state: PresenceState, unit: ExperienceUnit) -> list[str]:
    expire_lingering_moods(state)
    notes: list[str] = []
    mood_text = unit.feeling.effective_mood_span()
    if mood_text:
        days = resolve_linger_days(unit)
        _upsert_lingering(
            state,
            mood_text,
            days=days,
            source_unit_id=unit.id,
        )
        notes.append(f"lingering: mood ← unit {unit.id[:8]}")
    return notes


def apply_bundle_lingering(
    state: PresenceState,
    bundle: PresenceExperienceBundle,
) -> list[str]:
    expire_lingering_moods(state)
    notes: list[str] = []
    mood_text = bundle.mood_span.strip()
    if mood_text:
        days = bundle.linger_days if bundle.linger_days > 0 else LINGER_DAYS_DEFAULT
        _upsert_lingering(
            state,
            mood_text,
            days=days,
            source_unit_id=bundle.experience_id,
        )
        notes.append("lingering: mood ← life bundle")
    return notes
