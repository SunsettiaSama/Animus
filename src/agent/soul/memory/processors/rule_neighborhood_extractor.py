from __future__ import annotations

import re

from agent.soul.life.experience.unit import ExperienceUnit

from .neighborhood_extractor import NeighborhoodCandidate, NeighborhoodExtractorPort


class RuleNeighborhoodExtractor:
    """Phase 1??????????? LLM??"""

    def extract(self, unit: ExperienceUnit) -> list[NeighborhoodCandidate]:
        text = " ".join(
            part
            for part in (
                unit.situation.perception,
                unit.situation.narration,
                unit.action.content,
            )
            if part
        ).strip()
        if not text:
            return []
        candidates: list[NeighborhoodCandidate] = []
        candidates.append(
            NeighborhoodCandidate(
                label="????",
                content=text[:240],
            )
        )
        pet = re.search(r"(?|?|??)[^??]{0,20}(?|??|???)([^??\s]+)", text)
        if pet:
            candidates.append(
                NeighborhoodCandidate(
                    label="??",
                    content=pet.group(0)[:120],
                    related_labels=["??"],
                )
            )
        return candidates
