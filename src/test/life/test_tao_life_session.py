from __future__ import annotations

from unittest.mock import MagicMock

from agent.react.tao import TaoLoop, _PendingFinish


def test_pending_finish_carries_question_and_answer():
    pf = _PendingFinish(
        question="q",
        answer="a",
        processor=MagicMock(),
        persona_blocks=None,
    )
    assert pf.question == "q"
    assert pf.answer == "a"


def test_peek_pending_finish():
    tao = TaoLoop.__new__(TaoLoop)
    tao._pending_finish = _PendingFinish(
        question="q",
        answer="a",
        processor=MagicMock(),
        persona_blocks=None,
    )
    peek = tao.peek_pending_finish()
    assert peek is not None
    assert peek.question == "q"
