from __future__ import annotations

from unittest.mock import MagicMock

from agent.soul.speak.orchestrator.blocks.core.base import BlockContext
from agent.soul.speak.orchestrator.blocks.registry import BlockRegistry
from agent.soul.speak.orchestrator.bundle import SpeakPromptBundle
from agent.soul.speak.orchestrator.director.types import DirectorPlan, MemoryInjectPlan, ModuleDecision
from agent.soul.speak.orchestrator.guidance.layer import SpeakGuidanceLayer
from agent.soul.speak.orchestrator.system.reply_style import SpeakReplyStyle


def test_registry_apply_invokes_memory_block():
    bundle = SpeakPromptBundle(
        session_id="tao",
        guidance=SpeakGuidanceLayer(),
    )
    plan = DirectorPlan(
        session_id="tao",
        target_turn_index=1,
        modules=(
            ModuleDecision("memory", False, True, "test"),
            ModuleDecision("social", False, False, "test"),
        ),
        memory=MemoryInjectPlan(include_recall=True, include_portrait=False),
    )
    similar = MagicMock()
    orch = MagicMock()
    orch.io = MagicMock()
    orch.interactor_portrait = MagicMock()
    memory_compose = MagicMock()
    ctx = BlockContext(
        orchestrator=orch,
        io=orch.io,
        session_id="tao",
        turn_index=1,
        user_text="hi",
        mode="inbound",
        generation=0,
        reply_style=SpeakReplyStyle(),
        memory_compose=memory_compose,
        similar=similar,
    )
    BlockRegistry().apply(plan, bundle, ctx, include_social=False)
    memory_compose.apply_similar_memories.assert_called_once_with(bundle, similar)
