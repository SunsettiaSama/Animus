from __future__ import annotations

from agent.soul.life.experience.compression import build_unit_from_compression
from agent.soul.life.experience.memory_promotion import should_promote_to_memory
from agent.soul.memory.session.buffer import _parse_valence
from agent.soul.memory.session.types import DialogueCompressionBlock
from agent.soul.memory.domain import Valence
from agent.soul.speak.compose.context.structured_distill import distill_compression_block
from agent.soul.speak.compose.context.distiller import DialogueContextChunk


def test_compression_unit_carries_session_and_block_index():
    block = DialogueCompressionBlock(
        session_id="sess-1",
        block_index=2,
        summary="这轮对话让我印象深刻",
        emotion_label="专注",
        salience=0.72,
        transcript="用户：你好\n我：你好",
    )
    unit = build_unit_from_compression(block, interactor_id="alice")
    assert unit.situation.session_id == "sess-1"
    assert unit.situation.turn_index == 3
    assert "印象深刻" in unit.feeling.salience_note


def test_compression_block_promotes_via_regex_when_explicit():
    block = DialogueCompressionBlock(
        session_id="sess-1",
        block_index=0,
        summary="意外变故，久久不能平静",
        salience=0.8,
    )
    unit = build_unit_from_compression(block)
    assert should_promote_to_memory(unit) is True


def test_structured_distill_fallback_without_llm():
    batch = [
        DialogueContextChunk(user_text="今天天气不错", agent_text="是的"),
    ]
    block = distill_compression_block(
        None,
        session_id="tao",
        block_index=0,
        batch=batch,
        prior=[],
    )
    assert block.session_id == "tao"
    assert block.block_index == 0
    assert block.summary.strip()


def test_parse_valence_from_delta():
    assert _parse_valence("", 0.3) == Valence.positive
    assert _parse_valence("negative", 0.0) == Valence.negative
