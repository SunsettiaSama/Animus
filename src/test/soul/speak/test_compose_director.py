from __future__ import annotations

from unittest.mock import MagicMock

from agent.soul.speak.pipelines.request_driven.orchestrator.director.decide import decide_plan
from agent.soul.speak.pipelines.request_driven.orchestrator.director.memory import (
    build_memory_inject_plan,
    is_short_ack,
)
from agent.soul.speak.pipelines.request_driven.orchestrator.director.service import ComposeDirector
from agent.soul.speak.pipelines.request_driven.orchestrator.director.share import share_queue_full
from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.guidance import (
    GuidanceControlService,
    GuidancePlanInput,
)
from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.registry import BlockRegistry
from agent.soul.speak.pipelines.request_driven.orchestrator.pipeline.context import ComposePipelineContext
from agent.soul.speak.pipelines.request_driven.orchestrator.io import OrchestratorIOHub
from agent.soul.speak.pipelines.request_driven.orchestrator.io.inbound.guidance import GuidancePlanRequest
from config.soul.presence.config import SHARE_INTENT_QUEUE_MAX_ITEMS


def _orchestrator_mock(*, remaining_turns: int = 0, share_linked: bool = False):
    control = GuidanceControlService()
    if remaining_turns > 0:
        state = control.plan_and_set(
            GuidancePlanInput(
                session_id="tao",
                turn_index=1,
                distilled_context="延续话题。",
                persona_portrait="你是博物学家。",
                interactor_portrait="荧。",
                share_preview="",
                recall_preview="",
                trigger="init",
            )
        )
        state.remaining_turns = remaining_turns
    orchestrator = MagicMock()
    orchestrator.io = OrchestratorIOHub.from_control_service(control)
    orchestrator._presence = MagicMock()
    orchestrator._presence.snapshot.return_value = MagicMock()
    orchestrator._share = MagicMock()
    share_state = MagicMock()
    share_state.wants_share = False
    share_state.summary = ""
    share_state.events = ()
    share_state.count = 0
    orchestrator._share.collect.return_value = share_state
    orchestrator.share_compose_state.return_value = share_state
    orchestrator.block_registry = BlockRegistry()
    orchestrator.pipeline_context.side_effect = lambda **kwargs: ComposePipelineContext(
        orchestrator=orchestrator,
        **kwargs,
    )
    orchestrator.collect_share_count.return_value = 0
    orchestrator.uses_session_share_queue.return_value = False
    orchestrator._context = None
    orchestrator._session_port = None
    active = control.active("tao")
    if active is not None:
        active.share_linked = share_linked
    return orchestrator, control


def test_passive_gateway_requires_force():
    control = GuidanceControlService()
    io = OrchestratorIOHub.from_control_service(control)
    request = GuidancePlanRequest(
        session_id="tao",
        turn_index=1,
        trigger="turn",
    )
    assert io.inbound.guidance.sync_for_compose(request) is False
    assert io.inbound.guidance.sync_for_compose(request, force=True) is True


def test_short_ack_memory_plan_skips_recall():
    plan = build_memory_inject_plan(
        user_text="嗯",
        cold_start=False,
        arc_continues=True,
    )
    assert is_short_ack("嗯")
    assert plan.include_recall is False
    assert plan.request_emergence is False


def test_decide_guidance_arc_continues_without_refresh():
    orchestrator, _control = _orchestrator_mock(remaining_turns=2)
    plan = decide_plan(
        orchestrator,
        session_id="tao",
        target_turn_index=2,
        user_text="嗯",
        cold_start=False,
    )
    guidance = plan.decision_for("guidance")
    assert guidance is not None
    assert guidance.refresh is False
    assert guidance.include is True


def test_decide_share_queue_full_triggers_guidance_refresh():
    orchestrator, _control = _orchestrator_mock(remaining_turns=1, share_linked=False)
    share_state = MagicMock()
    share_state.wants_share = True
    share_state.summary = "地底蜥蜴"
    share_state.events = (MagicMock(index=0, topic="蜥蜴", share_desire=MagicMock(value="eager"), source="", salience=0.9, brief="蜥蜴"),)
    share_state.count = SHARE_INTENT_QUEUE_MAX_ITEMS
    orchestrator.share_compose_state.return_value = share_state
    plan = decide_plan(
        orchestrator,
        session_id="tao",
        target_turn_index=2,
        user_text="继续说",
        cold_start=False,
    )
    guidance = plan.decision_for("guidance")
    assert guidance is not None
    assert guidance.refresh is True
    assert guidance.guidance_trigger == "share_queue_full"
    assert share_queue_full(SHARE_INTENT_QUEUE_MAX_ITEMS)


def test_director_store_generation_invalidation():
    director = ComposeDirector(MagicMock())
    from agent.soul.speak.pipelines.request_driven.orchestrator.director.types import DirectorPlan

    plan = DirectorPlan(session_id="tao", target_turn_index=1, generation=0)
    director.save_plan(plan)
    assert director.load_plan("tao", 1) is not None
    director.invalidate_session("tao")
    assert director.load_plan("tao", 1) is None


def test_produce_plan_writes_next_turn():
    orchestrator, _control = _orchestrator_mock(remaining_turns=0)
    plan = decide_plan(
        orchestrator,
        session_id="tao",
        target_turn_index=2,
        user_text="你好",
        cold_start=True,
    )
    director = ComposeDirector(orchestrator)
    director.save_plan(plan)
    loaded = director.load_plan("tao", 2)
    assert loaded is not None
    assert loaded.target_turn_index == 2
