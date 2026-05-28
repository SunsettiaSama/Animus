from __future__ import annotations

from agent.interaction.core.continuity import (
    ContinuityInput,
    ContinuityVerdict,
    RuleBasedContinuityJudge,
)
from agent.interaction.core.context import InteractionContext
from agent.interaction.core.expectation import Expectation
from agent.interaction.core.semantic import SemanticInteraction


def _open_ix(stakes: str = "报告风险") -> SemanticInteraction:
    ctx = InteractionContext(session_id="tao", expectation=Expectation.required)
    return SemanticInteraction(context=ctx, stakes=stakes)


def test_no_active_opens_new():
    j = RuleBasedContinuityJudge()
    d = j.judge(ContinuityInput(active=None, incoming_user_text="你好"))
    assert d.verdict == ContinuityVerdict.close_and_new


def test_continue_phrase():
    j = RuleBasedContinuityJudge()
    ix = _open_ix()
    ix.append_user("帮我理风�?)
    ix.append_utterance("好的，有三点")
    d = j.judge(ContinuityInput(active=ix, incoming_user_text="展开第三�?))
    assert d.verdict == ContinuityVerdict.continue_same
    assert d.reason == "continue_phrase"


def test_break_phrase():
    j = RuleBasedContinuityJudge()
    ix = _open_ix()
    ix.append_user("理风�?)
    d = j.judge(ContinuityInput(active=ix, incoming_user_text="换个话题，明天天�?))
    assert d.verdict == ContinuityVerdict.close_and_new
    assert d.reason == "break_phrase"


def test_deferred_keeps_same():
    j = RuleBasedContinuityJudge()
    ix = _open_ix()
    ix.touch_expectation(Expectation.deferred)
    d = j.judge(ContinuityInput(active=ix, incoming_user_text="随便一�?))
    assert d.verdict == ContinuityVerdict.continue_same
    assert d.reason == "expectation_deferred"
