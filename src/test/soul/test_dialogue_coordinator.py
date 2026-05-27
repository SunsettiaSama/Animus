from __future__ import annotations

from unittest.mock import MagicMock

from agent.adapters.soul_dialogue import commit_turn_and_post_process, record_pending_turn
from agent.react.tao import TaoLoop, _PendingFinish
from agent.soul.life.experience.dialogue import close_dialogue_session
from agent.soul.life.experience.dialogue.coordinator import record_dialogue_turn


def test_record_dialogue_turn_delegates_to_experience_stack():
    stack = MagicMock()
    record_dialogue_turn(
        experience=stack,
        session_id="webui",
        user_text="q",
        agent_text="a",
    )
    stack.record_dialogue_turn.assert_called_once_with(
        session_id="webui",
        user_text="q",
        agent_text="a",
    )


def test_record_pending_turn_delegates_to_experience_stack():
    tao = TaoLoop.__new__(TaoLoop)
    tao._pending_finish = _PendingFinish(
        question="q",
        answer="a",
        processor=MagicMock(),
        persona_blocks=None,
    )
    stack = MagicMock()
    record_pending_turn(experience=stack, tao=tao, session_id="webui")
    stack.record_dialogue_turn.assert_called_once_with(
        session_id="webui",
        user_text="q",
        agent_text="a",
    )


def test_record_pending_turn_via_soul_experience_property():
    tao = TaoLoop.__new__(TaoLoop)
    tao._pending_finish = _PendingFinish(
        question="q",
        answer="a",
        processor=MagicMock(),
        persona_blocks=None,
    )
    stack = MagicMock()
    soul = MagicMock()
    soul.experience = stack
    record_pending_turn(soul=soul, tao=tao, session_id="webui")
    stack.record_dialogue_turn.assert_called_once_with(
        session_id="webui",
        user_text="q",
        agent_text="a",
    )


def test_commit_turn_and_post_process():
    tao = MagicMock()
    tao.peek_pending_finish.return_value = _PendingFinish(
        question="q",
        answer="a",
        processor=MagicMock(),
        persona_blocks=None,
    )
    stack = MagicMock()
    commit_turn_and_post_process(experience=stack, tao=tao, session_id="tao")
    stack.record_dialogue_turn.assert_called_once()
    tao.post_process.assert_called_once()


def test_close_dialogue_session():
    stack = MagicMock()
    close_dialogue_session(experience=stack, session_id="webui")
    stack.close_dialogue.assert_called_once_with("webui")
