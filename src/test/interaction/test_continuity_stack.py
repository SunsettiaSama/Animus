from __future__ import annotations

from agent.handler.continuity import CallableContinuityEmbedHandler, cosine_similarity
from agent.interaction.core.continuity import (
    ContinuityInput,
    ContinuityVerdict,
    StackedContinuityJudge,
)
from agent.interaction.core.context import InteractionContext
from agent.interaction.core.expectation import Expectation
from agent.interaction.core.semantic import SemanticInteraction


def _ix(stakes: str = "报告风险") -> SemanticInteraction:
    ctx = InteractionContext(session_id="tao", expectation=Expectation.required)
    ix = SemanticInteraction(context=ctx, stakes=stakes)
    ix.append_user("帮我分析报告风险�?)
    ix.append_utterance("好的")
    return ix


def _ortho_embed(text: str) -> list[float]:
    if "天气" in text:
        return [1.0, 0.0, 0.0]
    if "报告" in text or "风险" in text:
        return [0.0, 1.0, 0.0]
    return [0.0, 0.0, 1.0]


class _FakeContinuityLlm:
    def complete(self, system: str, user: str) -> str:
        if "天气" in user:
            return "BREAK\nreason: 新话�?
        return "CONTINUE\nreason: 同一�?


def test_embedding_breaks_topic():
    j = StackedContinuityJudge(
        embedder=CallableContinuityEmbedHandler(_ortho_embed),
        embedding_break_below=0.5,
        embedding_continue_above=0.9,
    )
    ix = _ix()
    d = j.judge(ContinuityInput(active=ix, incoming_user_text="明天天气怎么�?))
    assert d.verdict == ContinuityVerdict.close_and_new
    assert d.layer == "embedding"


def test_llm_when_embedding_gray():
    def _gray_embed(text: str) -> list[float]:
        if "天气" in text:
            return [0.7, 0.0, 0.7]
        return [1.0, 0.0, 0.0]

    j = StackedContinuityJudge(
        embedder=CallableContinuityEmbedHandler(_gray_embed),
        llm=_FakeContinuityLlm(),
        embedding_break_below=0.2,
        embedding_continue_above=0.95,
    )
    ix = _ix()
    d = j.judge(ContinuityInput(active=ix, incoming_user_text="明天天气怎么�?))
    assert d.verdict == ContinuityVerdict.close_and_new
    assert d.layer == "llm"


def test_cosine_orthogonal():
    assert cosine_similarity([1, 0, 0], [0, 1, 0]) == 0.0
