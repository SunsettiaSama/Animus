from __future__ import annotations

import json
import re

from .types import TaoRunResult


class ConsolidationTaoDecomposer:
    """从 Base Tao 回答拆解 ``SelfConceptDelta``（Tao 适配层，不在 Soul 核心）。"""

    @classmethod
    def decompose(cls, tao_result: TaoRunResult):
        from agent.soul.persona.self_concept.concept import SelfConceptDelta

        parsed = cls._parse_delta_payload(tao_result.answer)
        if parsed is not None:
            return parsed
        narrative = tao_result.answer.strip()[:300]
        if not narrative:
            trace_thoughts = [
                s.thought.strip()
                for s in tao_result.steps
                if s.thought.strip()
            ]
            if trace_thoughts:
                narrative = trace_thoughts[-1][:300]
        if not narrative:
            return SelfConceptDelta()
        return SelfConceptDelta(narrative=narrative)

    @classmethod
    def _parse_delta_payload(cls, raw: str):
        from agent.soul.persona.self_concept.concept import SelfConceptDelta

        text = raw.strip()
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if m:
            text = m.group(1).strip()
        m2 = re.search(r"\{[\s\S]*\}", text)
        if not m2:
            return None
        d = json.loads(m2.group(0))
        return SelfConceptDelta(
            narrative=str(d.get("narrative", "")).strip(),
            upgrades=list(d.get("upgrades") or []),
            adds=list(d.get("adds") or []),
            removes=[str(x) for x in d.get("removes") or [] if str(x).strip()],
        )
