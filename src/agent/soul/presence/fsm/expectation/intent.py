from __future__ import annotations

from typing import TYPE_CHECKING

from agent.soul.presence.share_desire import ShareDesire, max_share_desire, parse_share_desire, share_desire_weight

from .queue import ShareIntent, ShareIntentQueue
from .state import ExpectationState

if TYPE_CHECKING:
    from agent.soul.presence.transition.expectation import Expectation
    from agent.soul.presence.transition.interaction import PresenceInteraction

_NARRATIVE_KEYS = frozenset({"affect", "somatic", "working_memory", "thinking", "perception"})

_DIALOGUE_EXPECTATION_ALIASES: dict[str, str] = {
    "none": "none",
    "optional": "optional",
    "required": "required",
    "clarify": "clarify",
    "deferred": "deferred",
    "follow_up": "required",
    "follow-up": "required",
    "wait": "deferred",
}


def split_refresh_payload(raw: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    narratives: dict[str, str] = {}
    meta: dict[str, str] = {}
    for key, value in raw.items():
        text = str(value).strip() if value is not None else ""
        if key in _NARRATIVE_KEYS:
            narratives[key] = text
        else:
            meta[key] = text
    return narratives, meta


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "想", "要"}


def extract_share_intent(meta: dict[str, str], *, source: str) -> ShareIntent | None:
    wants = _parse_bool(meta.get("wants_to_share", ""))
    topic = meta.get("share_topic", "").strip()
    if not wants or not topic:
        return None
    desire = parse_share_desire(meta.get("share_desire"), default=ShareDesire.mild)
    salience = float(meta.get("share_salience", share_desire_weight(desire)) or 0.0)
    return ShareIntent(
        topic=topic,
        share_desire=desire,
        source=source,
        salience=salience,
    )


def apply_non_dialogue_share_refresh(
    expectation: ExpectationState,
    interaction: PresenceInteraction | None,
    meta: dict[str, str],
    *,
    source: str,
) -> list[str]:
    """非 dialogue 刷新：Agent 声明是否想分享 → 入队 + 累积 toward_user。"""
    intent = extract_share_intent(meta, source=source)
    if intent is None:
        return []
    expectation.share_queue.enqueue(intent)
    weight = share_desire_weight(intent.share_desire)
    expectation.accumulate_toward_user(
        weight,
        reason=intent.topic,
        source=source,
    )
    if interaction is not None:
        interaction.impulse_level = min(1.0, interaction.impulse_level + weight)
        interaction.impulse_reason = intent.topic
        interaction.impulse_source = source
        interaction.share_desire = max_share_desire(interaction.share_desire, intent.share_desire)
    return [f"share intent queued ({source}): {intent.topic[:48]}"]


def parse_dialogue_expectation(meta: dict[str, str]):
    from agent.soul.presence.transition.expectation import Expectation

    raw = meta.get("dialogue_expectation", "").strip().lower()
    if not raw:
        if _parse_bool(meta.get("wants_follow_up_reply", "")):
            return Expectation.required
        if _parse_bool(meta.get("needs_user_reply", "")):
            return Expectation.required
        return None
    if raw in _DIALOGUE_EXPECTATION_ALIASES:
        return Expectation(_DIALOGUE_EXPECTATION_ALIASES[raw])
    return Expectation(raw)


def apply_dialogue_interaction_expectation(
    interaction: PresenceInteraction,
    meta: dict[str, str],
) -> list[str]:
    from agent.soul.presence.transition.expectation import Expectation

    parsed = parse_dialogue_expectation(meta)
    if parsed is None:
        return []
    interaction.expectation = parsed
    return [f"dialogue expectation → {parsed.value}"]
