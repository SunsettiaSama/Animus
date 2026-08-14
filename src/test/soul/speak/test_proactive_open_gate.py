from __future__ import annotations

from types import SimpleNamespace

from agent.soul.presence.share_desire import ShareDesire
from agent.soul.presence.state.dynamic.expectation.package import ShareFoldedPackage
from agent.soul.presence.state.dynamic.expectation.queue import ShareIntent
from agent.soul.presence.transition.expectation import Expectation
from agent.soul.service import SoulService
from agent.soul.speak.io.outbound.request import SpeakRequest


def _request(*, entries=(), summary="") -> SpeakRequest:
    package = ShareFoldedPackage(
        summary=summary,
        entries=tuple(entries),
        peak_salience=0.4 if entries else 0.0,
        total_salience=0.4 if entries else 0.0,
        peak_share_desire=ShareDesire.mild if entries else ShareDesire.none,
        count=len(entries),
    )
    return SpeakRequest(
        session_id="tao",
        reason=summary,
        impulse_level=0.5,
        share_desire=ShareDesire.mild,
        expectation=Expectation.required,
        package=package,
        source="test",
    )


def _svc(*, queue_size: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        presence=SimpleNamespace(share_queue_size=lambda _sid: queue_size),
    )


def test_share_gate_rejects_empty_package_and_queue():
    svc = _svc(queue_size=0)
    assert SoulService._request_has_share_content(svc, _request()) is False


def test_share_gate_accepts_package_entries():
    svc = _svc(queue_size=0)
    intent = ShareIntent(topic="今晚月色很好", share_desire=ShareDesire.eager)
    assert SoulService._request_has_share_content(
        svc,
        _request(entries=(intent,), summary="今晚月色很好"),
    ) is True


def test_share_gate_accepts_live_share_queue():
    svc = _svc(queue_size=1)
    assert SoulService._request_has_share_content(svc, _request()) is True
