from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_ORCH = _ROOT / "agent" / "soul" / "speak" / "orchestrator"

for mod_name, filename in (
    ("agent.soul.speak.orchestrator.compose_slots", "compose_slots.py"),
    ("agent.soul.speak.orchestrator.compose_reconcile", "compose_reconcile.py"),
):
    path = _ORCH / filename
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)

ComposeReconcileAgent = sys.modules[
    "agent.soul.speak.orchestrator.compose_reconcile"
].ComposeReconcileAgent
SessionComposeSignals = type(
    "SessionComposeSignals",
    (),
    {
        "__init__": lambda self, **kw: self.__dict__.update(kw),
        "snapshot": lambda self: dict(self.__dict__),
    },
)


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


def test_reconcile_version_mismatch_forces_refresh():
    meta = {
        "persona_compose_version": 1,
        "scene_compose_version": 2,
        "guidance_compose_version": 3,
        "compose_session_turn": 1,
        "compose_session_generation": 1,
    }
    session = SessionComposeSignals(
        session_id="tao",
        turn_index=1,
        generation=1,
        interactor_id="tao",
    )
    plan = ComposeReconcileAgent().plan(
        bundle_meta=meta,
        io=_FakeIO(persona=2, scene=2, guidance=3),
        session=session,
    )
    persona = plan.directive_for("persona")
    scene = plan.directive_for("scene")
    guidance = plan.directive_for("guidance")
    assert persona.action == "refresh" and persona.force
    assert scene.action == "apply_only" and not scene.force
    assert guidance.action == "apply_only" and not guidance.force


def test_reconcile_session_turn_change_forces_all():
    meta = {"persona_compose_version": 2, "compose_session_turn": 0}
    session = SessionComposeSignals(
        session_id="tao",
        turn_index=2,
        generation=1,
        interactor_id="tao",
    )
    plan = ComposeReconcileAgent().plan(
        bundle_meta=meta,
        io=_FakeIO(persona=2, scene=2, guidance=2),
        session=session,
    )
    for block in ("persona", "scene", "guidance"):
        d = plan.directive_for(block)
        assert d.action == "refresh" and d.force
        assert "session_turn" in d.reason
