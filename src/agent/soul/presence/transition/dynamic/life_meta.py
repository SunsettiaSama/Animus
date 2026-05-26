from __future__ import annotations

from agent.soul.life.anchor.presence_bundle import PresenceExperienceBundle

from ...state.dynamic.expectation.intent import (
    apply_dialogue_interaction_expectation,
    apply_non_dialogue_share_refresh,
)
from ...state import PresenceState
from ..interaction import PresenceInteraction


def apply_dynamic_bundle(
    state: PresenceState,
    interaction: PresenceInteraction,
    bundle: PresenceExperienceBundle,
) -> list[str]:
    """life/反刍字段包 → 分享队列、冲动、对话期待（可触发后续 scan/speak）。"""
    notes: list[str] = []
    meta = bundle.meta_for_dynamic()
    if meta:
        notes.extend(
            apply_non_dialogue_share_refresh(
                state.expectation,
                interaction,
                meta,
                source=f"life:{bundle.source or 'bundle'}",
            )
        )
        notes.extend(apply_dialogue_interaction_expectation(interaction, meta))
    if not notes:
        notes.append("dynamic: no share/expectation meta")
    return notes
