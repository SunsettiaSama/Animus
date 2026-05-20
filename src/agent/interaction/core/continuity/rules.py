from __future__ import annotations

from ..expectation import Expectation
from .signals import ContinuitySignals, build_signals
from .types import ContinuityDecision, ContinuityInput, ContinuityVerdict


class RuleBasedContinuityJudge:
    """规则层：高置信 break/continue；默认保守延续（避免故事被切碎）。"""

    def __init__(
        self,
        *,
        idle_break_sec: float = 1800.0,
        max_idle_continue_sec: float = 300.0,
    ) -> None:
        self._idle_break_sec = idle_break_sec
        self._max_idle_continue_sec = max_idle_continue_sec

    def judge(self, data: ContinuityInput) -> ContinuityDecision:
        signals = build_signals(data)
        return self._decide(signals)

    def _decide(self, s: ContinuitySignals) -> ContinuityDecision:
        if not s.has_active or not s.active_open:
            return ContinuityDecision(
                ContinuityVerdict.close_and_new,
                reason="no_open_interaction",
                layer="hard",
            )

        if not s.incoming_stripped:
            return ContinuityDecision(
                ContinuityVerdict.continue_same,
                reason="empty_user_text",
                layer="hard",
            )

        if s.idle_seconds >= self._idle_break_sec:
            return ContinuityDecision(
                ContinuityVerdict.close_and_new,
                reason=f"idle>{self._idle_break_sec}s",
                layer="hard",
                confidence=0.95,
            )

        if s.break_phrase_hit:
            return ContinuityDecision(
                ContinuityVerdict.close_and_new,
                reason="break_phrase",
                layer="rule",
                confidence=0.9,
            )

        if s.agent_still_deferred:
            return ContinuityDecision(
                ContinuityVerdict.continue_same,
                reason="expectation_deferred",
                layer="rule",
            )

        if s.continue_phrase_hit:
            return ContinuityDecision(
                ContinuityVerdict.continue_same,
                reason="continue_phrase",
                layer="rule",
            )

        if s.is_backchannel and s.expectation in (
            Expectation.required,
            Expectation.clarify,
        ):
            return ContinuityDecision(
                ContinuityVerdict.continue_same,
                reason="backchannel_under_required",
                layer="rule",
            )

        if s.last_agent_had_question and s.incoming_len <= 200:
            return ContinuityDecision(
                ContinuityVerdict.continue_same,
                reason="answer_to_agent_question",
                layer="rule",
            )

        if s.idle_seconds > self._max_idle_continue_sec:
            return ContinuityDecision(
                ContinuityVerdict.close_and_new,
                reason=f"soft_idle>{self._max_idle_continue_sec}s",
                layer="rule",
                confidence=0.7,
            )

        return ContinuityDecision(
            ContinuityVerdict.continue_same,
            reason="default_continue",
            layer="hard_rule",
            confidence=0.55,
        )
