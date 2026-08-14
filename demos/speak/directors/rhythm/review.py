from __future__ import annotations

from typing import Any

from ...contracts import TextGenerator
from ...stage import StageState
from ...stage.review import RhythmReview
from ..base import extract_json_object, generate_text
from .prompts import REVIEW_SYSTEM, stage_brief_for_review


def parse_rhythm_review(payload: dict[str, Any]) -> RhythmReview:
    review = RhythmReview.from_payload(payload)
    if not review.abstract.strip():
        raise ValueError("rhythm.review: empty abstract")
    if not review.summary.strip():
        raise ValueError("rhythm.review: empty summary")
    return review


class SoftRhythmReviewSupplier:
    """Session-end pseudo-learning: dialogue curve -> abstract + summary."""

    def __init__(self, llm: TextGenerator) -> None:
        self._llm = llm

    def build_review(self, stage: StageState) -> RhythmReview:
        raw = generate_text(
            self._llm,
            system=REVIEW_SYSTEM,
            user=stage_brief_for_review(stage),
        )
        payload = extract_json_object(raw, director="rhythm.review")
        return parse_rhythm_review(payload)
