"""Deterministic work-intent prefilter: 你 + task verb → maybe_work."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field

from worker.work.types import WorkIntentSignal

# Central verb list — do not scatter synonyms into routers.
DEFAULT_TASK_VERBS: tuple[str, ...] = (
    "帮",
    "写",
    "改",
    "查",
    "找",
    "整理",
    "生成",
    "实现",
    "修",
    "运行",
    "执行",
    "测试",
    "总结",
    "分析",
    "创建",
    "重构",
    "检查",
    "修复",
)

_YOU_PATTERN = re.compile(r"你")


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    matched_terms: tuple[str, ...] = ()
    reason: str = ""
    confidence: float = 0.0


@dataclass
class WorkIntentMatcher:
    """Pure regex prefilter. No LLM, no side effects."""

    verbs: tuple[str, ...] = field(default_factory=lambda: DEFAULT_TASK_VERBS)
    you_pattern: re.Pattern[str] = field(default_factory=lambda: _YOU_PATTERN)

    def __post_init__(self) -> None:
        # Longer verbs first so「修复」wins over「修」.
        ordered = sorted(self.verbs, key=len, reverse=True)
        escaped = [re.escape(v) for v in ordered]
        object.__setattr__(self, "_verb_re", re.compile("|".join(escaped)))

    def match_text(self, text: str) -> MatchResult:
        question = str(text or "").strip()
        if not question:
            return MatchResult(matched=False, reason="empty_question")

        has_you = bool(self.you_pattern.search(question))
        verb_hits = tuple(dict.fromkeys(self._verb_re.findall(question)))
        if not has_you or not verb_hits:
            return MatchResult(matched=False, reason="no_you_and_verb")

        terms = ("你",) + verb_hits
        # Heuristic confidence: base + bonus per distinct verb, capped.
        confidence = min(0.55 + 0.1 * len(verb_hits), 0.95)
        return MatchResult(
            matched=True,
            matched_terms=terms,
            reason="you_and_task_verb",
            confidence=confidence,
        )

    def build_signal(
        self,
        question: str,
        *,
        session_id: str,
        channel_id: str,
        gen_id: str,
        work_id: str | None = None,
    ) -> WorkIntentSignal | None:
        result = self.match_text(question)
        if not result.matched:
            return None
        return WorkIntentSignal(
            work_id=work_id or str(uuid.uuid4()),
            session_id=session_id,
            channel_id=channel_id,
            gen_id=gen_id,
            question=str(question).strip(),
            matched_terms=list(result.matched_terms),
            reason=result.reason,
            confidence=result.confidence,
        )
