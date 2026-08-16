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
    """从 life 热存储拉取当下体验，折叠为 presence **static** 字段包（不含分享折叠）。"""
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
    enqueue = str(combined.get("enqueue_share", combined.get("wants_to_share", ""))).lower() in {
        "1", "true", "yes", "y",
    }
    push = str(combined.get("push_to_user", "")).lower() in {"1", "true", "yes", "y"}
    topic = str(combined.get("share_topic", "")).strip()
    content = str(combined.get("share_content", "") or topic).strip()
    narration = str(combined.get("thinking", "") or combined.get("narration", "")).strip()
    if not content and (enqueue or push):
        content = narration[:240]
    promote = str(combined.get("promote_to_memory", "")).lower() in {"1", "true", "yes", "y"}
    return PresenceExperienceBundle(
        session_id=block.session_id,
        channel_id=str(combined.get("target_channel_id", combined.get("channel_id", "")) or ""),
        source=block.kind.value,
        perception=str(combined.get("perception", "")),
        narration=narration,
        prior_thought=str(combined.get("working_memory", "") or combined.get("prior_thought", "")),
        emotion_label=str(combined.get("affect", "") or combined.get("emotion_label", "")),
        salience=float(combined.get("share_salience", combined.get("salience", 0.35)) or 0.35),
        enqueue_share=enqueue and bool(content),
        push_to_user=push and bool(content),
        share_content=content,
        share_why=str(combined.get("share_why", "") or ""),
        share_desire=str(combined.get("share_desire", "mild")),
        share_salience=float(combined.get("share_salience", combined.get("salience", 0.35)) or 0.35),
        promote_to_memory=promote,
        impression_intensity=float(combined.get("impression_intensity", 0.0) or 0.0),
        impression_why=str(combined.get("impression_why", "") or ""),
        annotation_decided=True,
        rumination_hint=str(combined.get("rumination_hint", "")) if block.kind == PresenceStateBlockKind.rumination else "",
        dialogue_expectation=str(combined.get("dialogue_expectation", "")),
    )


def rumination_presence_bundle(
    *,
    session_id: str = "tao",
    channel_id: str = "",
    hint: str = "",
    narration: str = "",
    salience: float = 0.35,
    enqueue_share: bool = False,
    push_to_user: bool = False,
    share_content: str = "",
    share_why: str = "",
    promote_to_memory: bool = False,
    impression_intensity: float = 0.0,
    impression_why: str = "",
) -> PresenceExperienceBundle:
    content = share_content.strip() or hint.strip() or narration.strip()
    return PresenceExperienceBundle(
        session_id=session_id,
        channel_id=channel_id,
        source="rumination",
        narration=narration.strip() or hint.strip(),
        rumination_hint=hint.strip(),
        salience=salience,
        enqueue_share=enqueue_share and bool(content),
        push_to_user=push_to_user and bool(content),
        share_content=content[:240] if (enqueue_share or push_to_user) else "",
        share_why=share_why,
        share_desire="mild",
        share_salience=salience,
        promote_to_memory=promote_to_memory,
        impression_intensity=impression_intensity,
        impression_why=impression_why,
        annotation_decided=True,
    )
