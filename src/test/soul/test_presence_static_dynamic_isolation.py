from __future__ import annotations

from agent.soul.presence import PresenceContext, PresenceEvent, PresenceService
from agent.soul.presence.transition import Expectation


def test_boundary_does_not_mutate_static_narrative():
    svc = PresenceService()
    session = svc._session("tao")
    session.state.affect.narrative = "静态情�?
    session.state.somatic.narrative = "静态身�?
    session.state.cognition.thinking = "静态思维"
    session.state.perception.narrative = "静态感�?

    svc.ingest(
        PresenceEvent.user_text("tao"),
        context=PresenceContext(line_open=True),
    )

    snap = svc.snapshot("tao")
    assert snap.state.affect.narrative == "静态情�?
    assert snap.state.somatic.narrative == "静态身�?
    assert snap.state.cognition.thinking == "静态思维"
    assert snap.state.perception.narrative == "静态感�?
    assert snap.expectation == Expectation.required


def test_patch_static_writes_narrative(tmp_path):
    from agent.soul.presence.share_desire import StaticStatePatch

    svc = PresenceService(life_dir=str(tmp_path))
    svc.patch_static("tao", StaticStatePatch(affect="新情�?))
    assert svc.snapshot("tao").state.affect.narrative == "新情�?
