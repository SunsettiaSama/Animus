from __future__ import annotations

from unittest.mock import MagicMock

from agent.soul.speak.responders.request_driven.orchestrator.directors.next_turn_guide import (
    NextTurnGuide,
    NextTurnGuideDirector,
    apply_next_turn_guide_output,
    promote_pending_next_turn_guide,
)
from agent.soul.speak.responders.request_driven.orchestrator.directors.think_trace import (
    DirectorThinkCompressor,
    DirectorThinkStep,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.core.types import (
    DialogueSnapshot,
    OrchestratorDomainSnapshot,
    SessionRuntimeSnapshot,
    SessionSignals,
    SessionSnapshot,
)
from agent.soul.speak.responders.request_driven.orchestrator.state.runtime.store import (
    SessionSchedulingState,
)
from agent.soul.speak.responders.request_driven.prompt import build_role_prompt
from agent.soul.speak.responders.request_driven.orchestrator.compose_manager.projectors.role_view import (
    RoleContextView,
)
from test.soul.persona.distill_fixtures import persona_snapshot_with_distill


def _snapshot(turn: int = 1) -> SessionSnapshot:
    return SessionSnapshot(
        schema_version=1,
        snapshot_id="snap",
        session_id="s1",
        signals=SessionSignals(session_id="s1", turn_index=turn, generation=0),
        runtime=SessionRuntimeSnapshot(),
        dialogue=DialogueSnapshot(user_text="你好"),
        orchestrator=OrchestratorDomainSnapshot(),
    )


def test_director_think_compress_action_keeps_action_and_result_only():
    step = DirectorThinkStep(
        think="长篇思考不应进入动作压缩单元",
        action="lookup_persona",
        result="冷静克制",
    )
    assert step.compress_unit() == "lookup_persona → 冷静克制"
    assert "长篇" not in step.compress_unit()

    think_only = DirectorThinkStep(think="下一轮先听后说")
    assert think_only.compress_unit() == "下一轮先听后说"

    compressor = DirectorThinkCompressor(chunk_size=2, max_unit_chars=200)
    assert compressor.record("s", step) is None
    summary = compressor.record(
        "s",
        DirectorThinkStep(think="收束", action="predict", result="ok"),
    )
    assert summary is not None
    assert "lookup_persona" in summary
    assert "predict" in summary
    assert "长篇思考" not in summary


def test_next_turn_guide_writes_pending_for_following_turn():
    orch = MagicMock()
    orch.persona_compose.query_persona_snapshot.return_value = persona_snapshot_with_distill(
        name="A"
    )
    orch.scene_compose.director_scene_brief.return_value = "海边营地 / 夜风"
    director = NextTurnGuideDirector(orch, llm=None)
    out = director.run(_snapshot(turn=3), user_text="今晚如何")
    assert out.payload["horizon"] == "next_turn"
    assert out.payload["target_turn"] == 4
    assert out.payload["produced_at_turn"] == 3
    assert "下一轮" in out.payload["behavior_guide"]
    assert "海边营地" in out.payload["script_hint"]

    state = SessionSchedulingState(session_id="s1")
    apply_next_turn_guide_output(state, out)
    assert state.pending_next_turn_guide["target_turn"] == 4

    active = promote_pending_next_turn_guide(state)
    assert active is not None
    assert active.target_turn == 4
    assert state.active_next_turn_guide["behavior_guide"]
    assert state.pending_next_turn_guide == {}


def test_role_prompt_consumes_active_behavior_guide():
    view = RoleContextView(session_id="s")
    prompt = build_role_prompt(
        view,
        user_text="嗨",
        behavior_guide="保持克制，先确认再回应",
        script_hint="仍在海边营地",
    )
    assert "上轮导演对当前轮的预测" in prompt.system_extra
    assert "保持克制" in prompt.system_extra
    assert "海边营地" in prompt.system_extra


def test_next_turn_guide_from_dict_roundtrip():
    guide = NextTurnGuide(
        behavior_guide="b",
        script_hint="s",
        produced_at_turn=1,
        target_turn=2,
        lookups=("persona",),
    )
    restored = NextTurnGuide.from_dict(guide.snapshot())
    assert restored is not None
    assert restored.behavior_guide == "b"
    assert restored.lookups == ("persona",)
