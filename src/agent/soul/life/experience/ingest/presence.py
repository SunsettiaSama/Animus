from __future__ import annotations

from agent.soul.life.anchor.presence_bundle import (
    PresenceExperienceBundle,
    merge_presence_bundles,
    presence_bundle_from_unit,
    read_presence_bundle,
)
from agent.soul.life.experience.domain.unit import ExperienceUnit
from agent.soul.life.experience.unit_layer.manage.log import ExperienceLog


def hot_units_for_session(
    log: ExperienceLog,
    session_id: str,
    *,
    hours: float | None = 2,
    tail: int = 12,
) -> list[ExperienceUnit]:
    recent = log.recent(hours=hours)
    matched = [
        u for u in recent
        if (u.situation.session_id or "tao") == session_id
        and u.source != "collision"
    ]
    if not matched:
        return []
    return matched[-tail:]


def supply_presence_bundle_from_life(
    log: ExperienceLog,
    session_id: str = "tao",
    *,
    hours: float | None = 2,
    tail: int = 12,
) -> PresenceExperienceBundle | None:
    """从 life 热存储拉取当下体验，折叠为 presence 转移字段包。"""
    units = hot_units_for_session(log, session_id, hours=hours, tail=tail)
    if not units:
        return None
    bundles: list[PresenceExperienceBundle] = []
    for unit in units:
        stored = read_presence_bundle(unit)
        bundles.append(stored if stored is not None else presence_bundle_from_unit(unit))
    return merge_presence_bundles(bundles)


def presence_bundle_from_state_block(block) -> PresenceExperienceBundle:
    from agent.soul.presence.state_block import PresenceStateBlockKind

    combined = {k: str(v) for k, v in block.narratives.items()}
    for key, value in block.meta.items():
        combined[key] = str(value)
    wants = str(combined.get("wants_to_share", "")).lower() in {"1", "true", "yes", "y"}
    topic = str(combined.get("share_topic", "")).strip()
    narration = str(combined.get("thinking", "") or combined.get("narration", "")).strip()
    return PresenceExperienceBundle(
        session_id=block.session_id,
        source=block.kind.value,
        perception=str(combined.get("perception", "")),
        narration=narration,
        prior_thought=str(combined.get("working_memory", "") or combined.get("prior_thought", "")),
        emotion_label=str(combined.get("affect", "") or combined.get("emotion_label", "")),
        salience=float(combined.get("share_salience", combined.get("salience", 0.35)) or 0.35),
        wants_to_share=wants and bool(topic or narration),
        share_topic=topic or narration[:120],
        share_desire=str(combined.get("share_desire", "mild")),
        rumination_hint=str(combined.get("rumination_hint", "")) if block.kind == PresenceStateBlockKind.rumination else "",
        dialogue_expectation=str(combined.get("dialogue_expectation", "")),
    )


def rumination_presence_bundle(
    *,
    session_id: str = "tao",
    hint: str = "",
    narration: str = "",
    salience: float = 0.35,
    wants_to_share: bool = False,
    share_topic: str = "",
) -> PresenceExperienceBundle:
    topic = share_topic.strip() or hint.strip() or narration.strip()
    return PresenceExperienceBundle(
        session_id=session_id,
        source="rumination",
        narration=narration.strip() or hint.strip(),
        rumination_hint=hint.strip(),
        salience=salience,
        wants_to_share=wants_to_share and bool(topic),
        share_topic=topic[:120] if wants_to_share else "",
        share_desire="mild",
        share_salience=salience,
    )
