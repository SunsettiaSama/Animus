from __future__ import annotations

"""Rule-based rhythm gate is intentionally disabled."""

from ...contracts import RhythmPlan
from ...stage import StageSnapshot


def rule_rhythm(snapshot: StageSnapshot) -> RhythmPlan:
    del snapshot
    raise RuntimeError(
        "rule_rhythm was removed: gate decisions must come from SoftChannel / LLM prompts, "
        "not emotion/urgency/idle numeric thresholds."
    )
