from __future__ import annotations

from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.core.ledger import stale_map


class _FakeOutbound:
    def __init__(self, versions: dict[str, int | None]) -> None:
        self._versions = versions

    def version(self, session_id: str) -> int | None:
        return self._versions.get(session_id)


class _FakeIO:
    def __init__(self, persona: int | None, scene: int | None, guidance: int | None) -> None:
        self.outbound = type(
            "Outbound",
            (),
            {
                "persona": _FakeOutbound({"tao": persona}),
                "scene": _FakeOutbound({"tao": scene}),
                "guidance": _FakeOutbound({"tao": guidance}),
            },
        )()


class _SessionSignals:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)

    def snapshot(self) -> dict[str, object]:
        return dict(self.__dict__)


def test_stale_version_mismatch():
    meta = {
        "persona_compose_version": 1,
        "scene_compose_version": 2,
        "guidance_compose_version": 3,
        "compose_session_turn": 1,
        "compose_session_generation": 1,
    }
    session = _SessionSignals(
        session_id="tao",
        turn_index=1,
        generation=1,
        interactor_id="tao",
    )
    io = _FakeIO(persona=2, scene=2, guidance=3)
    stale = stale_map(meta, io, session)
    assert stale["persona"] is True
    assert stale["scene"] is False
    assert stale["guidance"] is False


def test_stale_session_turn_change_forces_all():
    meta = {"persona_compose_version": 2, "compose_session_turn": 0}
    session = _SessionSignals(
        session_id="tao",
        turn_index=2,
        generation=1,
        interactor_id="tao",
    )
    io = _FakeIO(persona=2, scene=2, guidance=2)
    stale = stale_map(meta, io, session)
    for block in ("persona", "scene", "guidance"):
        assert stale[block] is True
