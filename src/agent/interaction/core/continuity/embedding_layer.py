from __future__ import annotations

from agent.handler.continuity import ContinuityEmbedHandler, cosine_similarity

from .signals import ContinuitySignals, build_signals
from .types import ContinuityDecision, ContinuityInput, ContinuityVerdict


class EmbeddingContinuityJudge:
    """第二层：embedding 语义相似度切断。

    低于 ``break_below`` → 新 Interaction；高于 ``continue_above`` → 延续。
    中间灰区返回 ``None``，交给 LLM 层。
    """

    def __init__(
        self,
        embedder: ContinuityEmbedHandler,
        *,
        break_below: float = 0.38,
        continue_above: float = 0.62,
    ) -> None:
        self._embedder = embedder
        self._break_below = break_below
        self._continue_above = continue_above

    def judge(
        self,
        data: ContinuityInput,
        signals: ContinuitySignals | None = None,
    ) -> ContinuityDecision | None:
        active = data.active
        text = (data.incoming_user_text or "").strip()
        if active is None or not active.is_open or not text:
            return None

        signals = signals or build_signals(data)
        if signals.break_phrase_hit or signals.agent_still_deferred:
            return None

        prior = active.continuity_digest(max_chars=800)
        if not prior:
            return None

        vec_new = self._embedder.embed(text)
        vec_prior = self._embedder.embed(prior)
        sim = cosine_similarity(vec_new, vec_prior)

        if sim <= self._break_below:
            return ContinuityDecision(
                ContinuityVerdict.close_and_new,
                reason=f"embedding_sim={sim:.3f}<={self._break_below}",
                layer="embedding",
                confidence=0.8,
            )

        if sim >= self._continue_above:
            return ContinuityDecision(
                ContinuityVerdict.continue_same,
                reason=f"embedding_sim={sim:.3f}>={self._continue_above}",
                layer="embedding",
                confidence=0.8,
            )

        return None
