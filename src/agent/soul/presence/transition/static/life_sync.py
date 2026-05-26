from __future__ import annotations

from agent.soul.life.anchor.presence_bundle import PresenceExperienceBundle

from ...state import PresenceState
from ...state.static import normalize_narrative


def apply_static_bundle(
    state: PresenceState,
    bundle: PresenceExperienceBundle,
) -> list[str]:
    """life 当下体验 → 五维静态自叙（不影响 interaction FSM）。"""
    notes: list[str] = []

    if bundle.perception.strip():
        state.perception.narrative = normalize_narrative(bundle.perception)
        notes.append("static: perception ← life")
    if bundle.narration.strip():
        state.cognition.thinking = normalize_narrative(bundle.narration)
        notes.append("static: thinking ← life narration")
    if bundle.prior_thought.strip() and not bundle.prior_thought.startswith("__"):
        wm = normalize_narrative(bundle.prior_thought)
        if wm:
            state.cognition.working_memory = wm
            notes.append("static: working_memory ← prior_thought")
    if bundle.emotion_label.strip():
        state.affect.narrative = normalize_narrative(bundle.emotion_label)
        notes.append("static: affect ← emotion_label")
    elif bundle.narration.strip() and not state.affect.narrative.strip():
        state.affect.append(bundle.narration[:80])
        notes.append("static: affect ← narration hint")

    if bundle.rumination_hint.strip() and bundle.rumination_hint not in state.affect.narrative:
        state.affect.append(bundle.rumination_hint[:120])
        notes.append("static: affect ← rumination")

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
