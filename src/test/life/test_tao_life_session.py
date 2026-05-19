from __future__ import annotations

from unittest.mock import MagicMock

from agent.react.tao import TaoLoop, _PendingFinish


def test_pending_finish_carries_life_session_id():
    pf = _PendingFinish(
        question="q",
        answer="a",
        processor=MagicMock(),
        persona_blocks=None,
        life_session_id="webui",
    )
    assert pf.life_session_id == "webui"


def test_set_life_interaction_session():
    tao = TaoLoop.__new__(TaoLoop)
    tao._life_session_id = "tao"
    tao._life = None
    tao.set_life_interaction_session("webui")
    assert tao._life_session_id == "webui"
