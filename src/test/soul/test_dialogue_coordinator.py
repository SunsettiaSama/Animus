from __future__ import annotations

from unittest.mock import MagicMock

from agent.react.tao import TaoLoop, _PendingFinish
from agent.soul.presence.experience.dialogue import (
    close_dialogue_session,
    commit_turn_and_post_process,
    record_pending_turn,
)


def test_record_pending_turn_delegates_to_soul():
    tao = TaoLoop.__new__(TaoLoop)
    tao._pending_finish = _PendingFinish(
        question="q",
        answer="a",
        processor=MagicMock(),
        persona_blocks=None,
    )
    soul = MagicMock()
    record_pending_turn(soul=soul, tao=tao, session_id="webui")
    soul.record_dialogue_turn.assert_called_once_with("q", "a", session_id="webui")


def test_commit_turn_and_post_process():
    tao = MagicMock()
    tao.peek_pending_finish.return_value = _PendingFinish(
        question="q",
        answer="a",
        processor=MagicMock(),
        persona_blocks=None,
    )
    soul = MagicMock()
    commit_turn_and_post_process(soul=soul, tao=tao, session_id="tao")
    soul.record_dialogue_turn.assert_called_once()
    tao.post_process.assert_called_once()


def test_close_dialogue_session():
    soul = MagicMock()
    close_dialogue_session(soul=soul, session_id="webui")
    soul.close_dialogue_interaction.assert_called_once_with("webui")
