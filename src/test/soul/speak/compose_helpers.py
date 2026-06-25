from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.core.base import BlockContext
from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.registry import BlockRegistry
from agent.soul.speak.pipelines.request_driven.orchestrator.director.types import DirectorPlan, ModuleDecision
from agent.soul.speak.pipelines.request_driven.orchestrator.frame import PreparedComposeFrame
from agent.soul.speak.pipelines.request_driven.orchestrator.system.reply_style import SpeakReplyStyle
from agent.soul.speak.pipelines.request_driven.orchestrator.system.build import build_system_layer
from agent.soul.speak.pipelines.request_driven.orchestrator.system.role import SpeakTurnMode


def _default_modules() -> tuple[ModuleDecision, ...]:
    return (
        ModuleDecision("persona", False, True, "test"),
        ModuleDecision("scene", False, True, "test"),
        ModuleDecision("guidance", True, True, "test", guidance_trigger="init"),
        ModuleDecision("context", False, True, "test"),
        ModuleDecision("memory", False, False, "test"),
        ModuleDecision("social", False, True, "test"),
        ModuleDecision("share", False, False, "test"),
    )


def _ensure_prepared_frame(
    plan: DirectorPlan,
    bundle,
    *,
    mode: SpeakTurnMode = "inbound",
) -> PreparedComposeFrame:
    if plan.prepared_frame is not None:
        return plan.prepared_frame
    frame = PreparedComposeFrame(
        session_id=plan.session_id,
        mode=mode,
        generation=plan.generation,
        system=build_system_layer(mode=mode, output_format=SpeakReplyStyle().render_prompt()),
        persona=bundle.persona,
        scene=bundle.scene,
        guidance=bundle.guidance,
    )
    plan.prepared_frame = frame
    return frame


def _minimal_orchestrator(io=None) -> MagicMock:
    orch = MagicMock()
    orch.io = io
    orch._presence = MagicMock()
    orch._share = MagicMock()
    share_state = MagicMock()
    share_state.count = 0
    share_state.events = ()
    share_state.summary = ""
    share_state.wants_share = False
    orch.share_compose_state.return_value = share_state
    orch.uses_session_share_queue.return_value = False
    orch._session_port = None
    orch._context = None
    orch.interactor_portrait = MagicMock()
    return orch


def finish_turn_for_test(
    bundle,
    *,
    social,
    session_id: str,
    user_text: str,
    turn_index: int,
    mode: SpeakTurnMode = "inbound",
    io=None,
    director_plan: DirectorPlan | None = None,
    story_port: Any | None = None,
    world_id_fn=None,
    orchestrator=None,
    **kwargs,
):
    """测试用 finish_turn：走 BlockRegistry，不依赖 TurnComposeAssembler。"""
    sid = session_id.strip()
    plan = director_plan or DirectorPlan(
        session_id=sid,
        target_turn_index=turn_index,
        modules=_default_modules(),
    )
    _ensure_prepared_frame(plan, bundle, mode=mode)
    orch = orchestrator or _minimal_orchestrator(io)
    if io is not None:
        orch.io = io
    ctx = BlockContext(
        orchestrator=orch,
        io=orch.io,
        session_id=sid,
        turn_index=turn_index,
        user_text=user_text,
        mode=mode,
        generation=plan.generation,
        reply_style=SpeakReplyStyle(),
        share_queue_count=0,
        use_session_share_queue=False,
        social=social,
        story_port=story_port,
        world_id_fn=world_id_fn,
        session_port=orch._session_port,
    )
    registry = BlockRegistry()
    registry.apply(plan, bundle, ctx, include_social=True)
    return bundle
