from __future__ import annotations

from unittest.mock import MagicMock

from agent.soul.speak.io.outbound import SpeakPresenceOutbound, SpeakRequest
from agent.soul.presence.state import ShareFoldedPackage
from agent.soul.presence.share_desire import ShareDesire
from agent.soul.presence.transition.expectation import Expectation


def test_speak_outbound_blocks_proactive_when_required():
    soul = MagicMock()
    snap = MagicMock()
    snap.expectation.value = Expectation.required.value
    soul.presence.snapshot.return_value = snap

    outbound = SpeakPresenceOutbound(soul)
    result = outbound.deliver_agent_message(
        session_id="tao",
        message="想聊�?,
        wait_reply=True,
        append=False,
    )
    assert result["ok"] is False
    assert result["blocked"] is True
    soul.record_dialogue_turn.assert_not_called()


def test_speak_outbound_handle_expectation_append():
    soul = MagicMock()
    snap = MagicMock()
    snap.expectation.value = Expectation.optional.value
    soul.presence.snapshot.return_value = snap
    soul.start_dialogue_session.return_value = {"ok": True}
    speak_service = MagicMock()
    speak_service.deliver_agent_message.return_value = {
        "ok": True,
        "session_id": "tao",
        "message": "补充一�?,
        "exchange_id": "ex-1",
    }
    soul._ensure_speak_service.return_value = speak_service

    outbound = SpeakPresenceOutbound(soul)
    request = SpeakRequest(
        session_id="tao",
        reason="补充一�?,
        impulse_level=0.4,
        share_desire=ShareDesire.moderate,
        expectation=Expectation.optional,
        package=ShareFoldedPackage(
            summary="补充一�?,
            entries=(),
            peak_salience=0.0,
            total_salience=0.0,
            peak_share_desire=ShareDesire.moderate,
            count=0,
        ),
        source="expectation_scan:append",
        wait_reply=False,
    )
    result = outbound.handle(request)
    assert result["ok"] is True
    assert result["append"] is True
    speak_service.deliver_agent_message.assert_called_once()
    soul.presence.bind.assert_called_once_with("tao", expectation=Expectation.optional)
