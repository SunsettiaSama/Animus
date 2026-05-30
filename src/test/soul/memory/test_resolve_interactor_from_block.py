from __future__ import annotations

from agent.soul.life.experience.domain.anchor_codec import AnchorUnitContext, InteractionDirection, stamp_anchor_context
from agent.soul.life.experience.domain.unit import (
    ExperienceAction,
    ExperienceActionKind,
    ExperienceFeeling,
    ExperienceSituation,
    ExperienceUnit,
)
from agent.soul.memory.graph.networks.experience_block import resolve_interactor_id
from agent.soul.memory.io.session import DialogueCompressionBlock
from agent.soul.life.experience.unit_layer.create import build_unit_from_compression


def _minimal_unit(**kwargs) -> ExperienceUnit:
    return ExperienceUnit.make(
        situation=ExperienceSituation(session_id=kwargs.get("session_id", "")),
        action=ExperienceAction(kind=ExperienceActionKind.speaking, content=""),
        feeling=ExperienceFeeling(),
    )


def test_resolve_interactor_from_anchor_context():
    unit = _minimal_unit(session_id="sess-1")
    stamp_anchor_context(
        unit,
        AnchorUnitContext(
            direction=InteractionDirection.inbound,
            session_id="sess-1",
            interactor_id="visitor-42",
        ),
    )
    assert resolve_interactor_id(unit) == "visitor-42"


def test_resolve_interactor_does_not_fallback_to_session_for_event():
    unit = _minimal_unit(session_id="sess-only")
    assert resolve_interactor_id(unit) == ""


def test_compression_block_interactor_on_unit():
    block = DialogueCompressionBlock(
        session_id="sess-1",
        block_index=0,
        summary="聊了几句",
        transcript="用户：你好",
        interactor_id="visitor-99",
    )
    unit = build_unit_from_compression(block, interactor_id="visitor-99")
    from agent.soul.life.experience.domain.anchor_codec import read_anchor_context

    ctx = read_anchor_context(unit)
    assert ctx is not None
    assert ctx.interactor_id == "visitor-99"
    assert ctx.session_id == "sess-1"
