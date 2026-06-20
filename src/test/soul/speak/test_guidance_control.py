from __future__ import annotations

from unittest.mock import MagicMock

from test.soul.speak.compose_helpers import finish_turn_for_test as finish_turn_bundle
from agent.soul.speak.orchestrator.bundle import SpeakPromptBundle
from agent.soul.speak.orchestrator.guidance.control import (
    GuidanceControlService,
    GuidancePlanInput,
    NARRATIVE_MAX_CHARS,
)
from agent.soul.speak.orchestrator.guidance.layer import SpeakGuidanceLayer
from agent.soul.speak.orchestrator.io import OrchestratorIOHub
from agent.soul.speak.orchestrator.io.inbound.guidance import GuidancePlanRequest
from agent.soul.speak.orchestrator.persona import SpeakPersonaLayer
from agent.soul.speak.session.manage.coordinator import SessionSocialManager
from config.soul.presence.config import SHARE_INTENT_QUEUE_MAX_ITEMS


def _registry_mock(*, turn_index: int = 3):
    registry = MagicMock()
    registry.get.return_value = MagicMock(generation=1)
    registry.current_turn_index.return_value = turn_index
    return registry


def test_control_state_narrative_is_capped_and_has_version():
    control = GuidanceControlService()
    state = control.plan_and_set(
        GuidancePlanInput(
            session_id="tao",
            turn_index=1,
            distilled_context="你们在去冒险家协会的路上偶遇。",
            persona_portrait="你是博物学家，开朗乐观。",
            interactor_portrait="荧，好朋友。",
            share_preview="",
            recall_preview="",
            last_rhythm_brief="",
            share_queue_count=0,
            share_queue_full=False,
            trigger="init",
        )
    )
    assert state.version == 1
    assert len(state.narrative) <= NARRATIVE_MAX_CHARS
    assert "用户" in state.narrative
    assert "你" in state.narrative


def test_share_queue_full_triggers_control_refresh():
    control = GuidanceControlService()
    io = OrchestratorIOHub.from_control_service(control)
    request = GuidancePlanRequest(
        session_id="tao",
        turn_index=2,
        distilled_context="近期对话：互相打了招呼。",
        persona_portrait="你是博物学家。",
        interactor_portrait="荧。",
        share_preview="- [0] 地底蜥蜴（意愿：strong）",
        share_queue_count=SHARE_INTENT_QUEUE_MAX_ITEMS,
        share_queue_full=True,
        trigger="share_queue_full",
    )
    assert io.inbound.guidance.sync_for_compose(request, force=True) is True
    snapshot = io.outbound.guidance.snapshot("tao")
    assert snapshot is not None
    assert snapshot["share_linked"] is True


def test_finish_turn_bundle_injects_guidance_narrative():
    control = GuidanceControlService()
    io = OrchestratorIOHub.from_control_service(control)
    social = SessionSocialManager(registry=_registry_mock())
    persona = SpeakPersonaLayer()
    persona.self_narrative = "你是博物学家。"
    persona.dialogue_compressed = "你们在路上偶遇。"
    bundle = SpeakPromptBundle(
        session_id="tao",
        persona=persona,
        guidance=SpeakGuidanceLayer(
            interactor_portrait="荧。",
            recall_preview="- 上次在纳塔地底见过蜥蜴",
        ),
    )
    from agent.soul.speak.orchestrator.director.types import DirectorPlan, ModuleDecision

    director_plan = DirectorPlan(
        session_id="tao",
        target_turn_index=2,
        modules=(
            ModuleDecision("persona", False, True, "test"),
            ModuleDecision("scene", False, True, "test"),
            ModuleDecision("guidance", True, True, "test", guidance_trigger="init"),
            ModuleDecision("context", False, True, "test"),
            ModuleDecision("memory", False, True, "test"),
            ModuleDecision("social", False, False, "test"),
            ModuleDecision("share", False, False, "test"),
        ),
    )
    finish_turn_bundle(
        bundle,
        social=social,
        session_id="tao",
        user_text="嗨",
        turn_index=2,
        io=io,
        share_queue_count=0,
        director_plan=director_plan,
    )
    assert "用户" in bundle.guidance.control_arc and "你" in bundle.guidance.control_arc
    assert bundle.meta.get("guidance_control_version") == 1


def test_version_increments_on_replan():
    control = GuidanceControlService()
    io = OrchestratorIOHub.from_control_service(control)
    base = GuidancePlanRequest(session_id="tao", turn_index=1, trigger="init")
    io.inbound.guidance.plan(base)
    io.inbound.guidance.plan(base)
    assert io.outbound.guidance.version("tao") == 2


def test_clear_control_arc():
    control = GuidanceControlService()
    io = OrchestratorIOHub.from_control_service(control)
    io.inbound.guidance.plan(GuidancePlanRequest(session_id="tao", turn_index=1, trigger="init"))
    io.inbound.guidance.clear_control_arc("tao")
    assert io.outbound.guidance.snapshot("tao") is None


def test_recall_candidates_penalize_repeat_pick():
    from types import SimpleNamespace

    from agent.soul.speak.orchestrator.guidance.memory.candidates import (
        build_recall_candidates_from_pull,
    )
    from agent.soul.speak.orchestrator.guidance.memory.pick_weights import (
        PICK_PENALTY_FACTOR,
        PICK_WEIGHT_FLOOR,
    )
    from agent.soul.speak.orchestrator.queue.memory import ComposeMemoryBuffer

    buffer = ComposeMemoryBuffer()
    session_id = "tao"
    pulled = SimpleNamespace(
        social_prefetch_lines=["唯一 social"],
        social_prefetch_unit_ids=["soc-1"],
        warm_spread_lines=[],
        warm_spread_unit_ids=[],
        inject=SimpleNamespace(lines=[], unit_ids=[]),
    )
    first = build_recall_candidates_from_pull(
        pulled,
        session_id=session_id,
        pick_weights=buffer,
    )
    assert len(first) == 1
    assert first[0].unit_id == "soc-1"
    weight_after = buffer.recall_pick_weight(session_id, "soc-1")
    assert weight_after == max(PICK_WEIGHT_FLOOR, PICK_PENALTY_FACTOR)
    assert weight_after < 1.0


def test_planner_json_emit_resolves_queue_index():
    from agent.soul.speak.orchestrator.guidance.control.planner import (
        GuidancePlanInput,
        _state_from_parsed,
        _ParsedPlan,
    )
    from agent.soul.speak.orchestrator.guidance.share.candidates import SharePlannerCandidate

    data = GuidancePlanInput(
        session_id="tao",
        turn_index=1,
        distilled_context="",
        persona_portrait="",
        interactor_portrait="",
        share_preview="- [0] topic",
        recall_preview="",
        share_candidates=(
            SharePlannerCandidate(
                planner_index=0,
                queue_index=2,
                brief="topic",
                share_desire="eager",
                salience=0.9,
            ),
        ),
        recall_candidates=(),
        share_queue_count=1,
        share_queue_full=False,
        trigger="turn",
    )
    state = _state_from_parsed(
        data,
        _ParsedPlan(
            narrative="用户还在。你心里有话想说（分享：topic）。接下来轻轻抛出引子。",
            emit_share_index=0,
            emit_recall_index=None,
        ),
        version=1,
    )
    assert state.emit_share_queue_index == 2
    assert state.share_linked is True


def test_fallback_does_not_force_share_or_recall_tags():
    control = GuidanceControlService()
    state = control.plan_and_set(
        GuidancePlanInput(
            session_id="tao",
            turn_index=2,
            distilled_context="你们在去冒险家协会的路上偶遇。",
            persona_portrait="你是博物学家。",
            interactor_portrait="荧。",
            share_preview="- [0] 地底蜥蜴（意愿：strong）",
            recall_preview="- 曾在雨夜与同伴失散",
            last_rhythm_brief="",
            share_queue_count=SHARE_INTENT_QUEUE_MAX_ITEMS,
            share_queue_full=True,
            trigger="share_queue_full",
        )
    )
    assert "（分享：" not in state.narrative
    assert "（回忆：" not in state.narrative
    assert state.share_linked is True


def test_on_turn_complete_consumes_remaining_turns():
    control = GuidanceControlService()
    control.plan_and_set(
        GuidancePlanInput(
            session_id="tao",
            turn_index=1,
            distilled_context="",
            persona_portrait="",
            interactor_portrait="",
            share_preview="",
            recall_preview="",
            last_rhythm_brief="",
            share_queue_count=0,
            share_queue_full=False,
            trigger="init",
        )
    )
    control.on_turn_complete("tao", session_state="finish")
    active = control.active("tao")
    assert active is not None
    assert active.remaining_turns == 2
