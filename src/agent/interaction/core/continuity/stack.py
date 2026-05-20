from __future__ import annotations

from agent.handler.continuity import ContinuityEmbedHandler, ContinuityLlmHandler

from .embedding_layer import EmbeddingContinuityJudge
from .llm_layer import LlmContinuityJudge
from .rules import RuleBasedContinuityJudge
from .signals import build_signals
from .types import ContinuityDecision, ContinuityInput, ContinuityJudge, ContinuityVerdict


class StackedContinuityJudge:
    """三层连续性：硬规则 → embedding → LLM handler。

    任一层高置信命中即返回；embedding 灰区才调 LLM；无 LLM 时回退规则默认。
    """

    def __init__(
        self,
        *,
        rules: RuleBasedContinuityJudge | None = None,
        embedder: ContinuityEmbedHandler | None = None,
        llm: ContinuityLlmHandler | None = None,
        rule_confidence_floor: float = 0.85,
        embedding_break_below: float = 0.38,
        embedding_continue_above: float = 0.62,
    ) -> None:
        self._rules = rules or RuleBasedContinuityJudge()
        self._embedding = (
            EmbeddingContinuityJudge(
                embedder,
                break_below=embedding_break_below,
                continue_above=embedding_continue_above,
            )
            if embedder is not None
            else None
        )
        self._llm = LlmContinuityJudge(llm) if llm is not None else None
        self._rule_floor = rule_confidence_floor

    def judge(self, data: ContinuityInput) -> ContinuityDecision:
        signals = build_signals(data)
        rule_decision = self._rules.judge(data)

        if rule_decision.confidence >= self._rule_floor:
            return rule_decision

        if rule_decision.verdict == ContinuityVerdict.close_and_new:
            return rule_decision

        if self._embedding is not None:
            emb = self._embedding.judge(data, signals)
            if emb is not None:
                return emb

        if self._llm is not None:
            return self._llm.judge(data, signals)

        return rule_decision


# 默认对外：实现 ContinuityJudge 协议
DefaultContinuityJudge = StackedContinuityJudge
