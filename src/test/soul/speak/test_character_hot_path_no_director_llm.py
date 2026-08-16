"""用户→角色热路径不得同步打导演 plan_control_arc / bootstrap LLM。"""

from __future__ import annotations

from unittest.mock import MagicMock

from agent.soul.speak.llm.engine import SpeakLLMEngine
from agent.soul.speak.responders.request_driven.orchestrator import SpeakOrchestrator
from agent.soul.speak.responders.request_driven.orchestrator.director.decide import (
    decide_hot_path_plan,
)
from agent.soul.speak.responders.request_driven.orchestrator.runner import SpeakComposeRunner
from agent.soul.speak.responders.request_driven.orchestrator.turn_coordinator import (
    OrchestratorTurnCoordinator,
)
from agent.soul.speak.service import SpeakService
from test.soul.persona.distill_fixtures import persona_snapshot_with_distill
from test.soul.speak._life_outbound_mock import RecordingSpeakLifeOutbound


class _FakeLLM:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate_messages(self, messages):
        self.calls.append("generate_messages")
        del messages
        return '{"narrative": "should_not_run_on_hot_path", "emit_share_index": null, "emit_recall_index": null}'

    def stream_generate_messages(self, messages):
        del messages
        yield "<speak>ok</speak>"

    def generate(self, user_text, system=""):
        self.calls.append(f"generate:{system[:24]}")
        return self.generate_messages([])


def test_decide_hot_path_never_refreshes_llm_blocks():
    plan = decide_hot_path_plan(
        session_id="s1",
        target_turn_index=1,
        user_text="在干啥呢",
    )
    assert "director: hot_path_no_llm_refresh" in plan.notes
    for mod in plan.modules:
        if mod.block in {"persona", "scene", "guidance"}:
            assert mod.refresh is False


def test_kick_on_user_input_uses_hot_path_not_bootstrap(monkeypatch):
    soul = MagicMock()
    soul.get_persona_snapshot.return_value = persona_snapshot_with_distill(name="A")
    presence = MagicMock()
    orch = SpeakOrchestrator(soul, presence)
    runner = SpeakComposeRunner()
    coord = OrchestratorTurnCoordinator(orch, compose_runner=runner, compose_wait_ms=0)

    boot_calls: list[str] = []
    warm_calls: list[int] = []

    def _boot(*_a, **_k):
        boot_calls.append("bootstrap")
        raise AssertionError("user hot path must not bootstrap_plan")

    monkeypatch.setattr(orch.compose_director, "bootstrap_plan", _boot)
    monkeypatch.setattr(
        runner,
        "schedule_plan_warm",
        lambda *_a, **k: warm_calls.append(int(k.get("target_turn_index") or 0)),
    )

    memory = MagicMock()
    state = coord.kick_on_user_input(
        "live:hot",
        "在干啥呢，借我瞅瞅",
        turn_index=1,
        memory_compose=memory,
        generation=0,
        mode="inbound",
    )
    assert boot_calls == []
    assert "turn_coordinator: hot_path_no_sync_director_llm" in state.notes
    assert 1 in warm_calls and 2 in warm_calls
    plan = orch.compose_director.load_plan("live:hot", 1)
    assert plan is not None
    assert plan.prepared_frame is not None
    assert any("hot_path" in n for n in plan.notes)


def test_compose_bundle_inbound_skips_bootstrap_llm(monkeypatch):
    fake = _FakeLLM()
    soul = MagicMock()
    soul.get_persona_snapshot.return_value = persona_snapshot_with_distill(name="A")
    presence = MagicMock()
    snap = MagicMock()
    snap.state.affect.render.return_value = ""
    snap.state.somatic.render.return_value = ""
    snap.state.cognition.render.return_value = ""
    snap.state.perception.render.return_value = ""
    snap.state.expectation.toward_user = 0.0
    snap.state.expectation.to_dict.return_value = {"share_queue": {"items": []}}
    snap.interaction.impulse_reason = ""
    presence.snapshot.return_value = snap

    service = SpeakService(
        persona=soul,
        presence=presence,
        llm_engine=SpeakLLMEngine(fake),
        orchestrator=SpeakOrchestrator(soul, presence, guidance_llm=SpeakLLMEngine(fake)),
        life_outbound=RecordingSpeakLifeOutbound(),
        life_lifecycle=None,
    )

    boot_calls: list[str] = []

    def _boot(*_a, **_k):
        boot_calls.append("bootstrap")
        raise AssertionError("inbound compose must not bootstrap_plan")

    monkeypatch.setattr(
        service._orchestrator.compose_director,
        "bootstrap_plan",
        _boot,
    )
    monkeypatch.setattr(
        service._memory_compose,
        "pull_compose_context",
        lambda *_a, **_k: (
            MagicMock(sources=(), inject=MagicMock(lines=()), spilled=MagicMock(lines=())),
            MagicMock(interactor_id="", turn_index=1, portrait_text=""),
        ),
    )

    bundle = service._compose_bundle(
        "live:compose-hot",
        "借我瞅瞅",
        mode="inbound",
        turn_index=1,
    )
    assert boot_calls == []
    assert "plan_control" not in " ".join(fake.calls)
    assert bundle.session_id == "live:compose-hot"
