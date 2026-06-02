from __future__ import annotations

from agent.soul.life.anchor.presence_bundle import PresenceExperienceBundle

from ...lingering import apply_bundle_lingering
from ...state import PresenceState
from ...state.static import normalize_narrative


def apply_static_bundle(
    state: PresenceState,
    bundle: PresenceExperienceBundle,
) -> list[str]:
    """life 当下体验 → 静态自叙（perception/cognition）；时段情绪写入 lingering，不刷 Speak 可见 affect。"""
    notes: list[str] = []

    if bundle.perception.strip():
        state.perception.narrative = normalize_narrative(bundle.perception)
        notes.append("static: perception ← life")
    narration = bundle.subjective_narrative.strip() or bundle.narration.strip()
    if narration:
        state.cognition.thinking = normalize_narrative(narration)
        notes.append("static: thinking ← life narration")

    notes.extend(apply_bundle_lingering(state, bundle))

    if bundle.valence_delta != 0.0 or bundle.arousal_delta != 0.0:
        somatic_bits: list[str] = []
        if bundle.arousal_delta > 0.15:
            somatic_bits.append("身体偏紧绷")
        elif bundle.arousal_delta < -0.15:
            somatic_bits.append("身体偏放松")
        if bundle.valence_delta > 0.15:
            somatic_bits.append("心绪偏亮")
        elif bundle.valence_delta < -0.15:
            somatic_bits.append("心绪偏沉")
        if somatic_bits:
            state.somatic.narrative = "，".join(somatic_bits)
            notes.append("static: somatic ← feeling delta")

    if not notes:
        notes.append("static: no narrative fields to apply")
    return notes
