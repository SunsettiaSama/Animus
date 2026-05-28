from __future__ import annotations

from agent.soul.speak.session.lifecycle.hold.semantic import TopicShiftSemanticBoundary
from agent.soul.speak.session import SpeakTurnChunk


def test_semantic_boundary_detects_explicit_marker():
    boundary = TopicShiftSemanticBoundary()
    chunk = SpeakTurnChunk(session_id="tao", user_text="/new 聊聊别的", agent_text="�?)
    assert boundary.should_rotate("tao", last_turn=chunk) is True
    assert boundary.reason() == "explicit marker: /new"
