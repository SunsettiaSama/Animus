from __future__ import annotations

import re

from agent.soul.life.experience.unit import ExperienceUnit

from .neighborhood_extractor import NeighborhoodCandidate, NeighborhoodExtractorPort


class RuleNeighborhoodExtractor:
    """Phase 1：规则抽取邻域事件（�?LLM）�?""

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
                label="对话摘要",
                content=text[:240],
            )
        )
        pet = re.search(r"(猫|狗|宠物)[^，。]{0,20}(叫|名为|名字�?([^，。\s]+)", text)
        if pet:
            candidates.append(
                NeighborhoodCandidate(
                    label="宠物",
                    content=pet.group(0)[:120],
                    related_labels=["宠物"],
                )
            )
        return candidates
