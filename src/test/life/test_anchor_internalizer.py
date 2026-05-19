from __future__ import annotations

from agent.soul.life.anchor.internalization import AnchorInternalizer, synthesize_interaction_unit
from agent.soul.life.anchor.internalization.session import InteractionSession
from agent.soul.life.anchor.internalization.turn import InteractionTurn
from agent.soul.life.anchor.inbound.recorder import InboundRecorder
from agent.soul.life.anchor.chronicle import AnchorChronicleKind, AnchorChronicleStore
from agent.soul.life.experience.anchor_codec import InteractionDirection, read_anchor_context
from agent.soul.life.experience.log import ExperienceLog
from agent.soul.life.orchestrator import ExperienceOrchestrator


def _setup(tmp_path):
    life_dir = str(tmp_path)
    log = ExperienceLog(life_dir)
    orch = ExperienceOrchestrator(log=log)
    chronicle = AnchorChronicleStore(life_dir)
    inbound = InboundRecorder(orch, chronicle)
    internalizer = AnchorInternalizer(inbound, orch, chronicle, idle_close_sec=60.0)
    return internalizer, orch, chronicle


def test_session_synthesize_multi_turn(tmp_path):
    session = InteractionSession(session_id="tao", direction=InteractionDirection.inbound)
    session.turns = [
        InteractionTurn(1, "你好", "嗨", salience=0.3),
        InteractionTurn(2, "聊聊架构", "好的", salience=0.5, emotion_label="专注"),
    ]
    unit = synthesize_interaction_unit(session)
    assert unit.source == "interaction"
    assert unit.situation.turn_index == 2
    assert "2 轮" in unit.situation.narration
    ctx = read_anchor_context(unit)
    assert ctx is not None
    assert ctx.interaction_id == session.id


def test_close_interaction_ingests_session_unit(tmp_path):
    internalizer, orch, chronicle = _setup(tmp_path)
    internalizer.append_inbound_turn("tao", "q1", "a1", salience=0.3)
    internalizer.append_inbound_turn("tao", "q2", "a2", salience=0.4)
    unit = internalizer.close_interaction("tao")
    assert unit is not None
    assert unit.source == "interaction"
    hot = orch._log.recent()
    assert any(u.source == "interaction" for u in hot)
    kinds = [e.kind for e in chronicle.recent_days(1)]
    assert AnchorChronicleKind.user_turn in kinds
    assert AnchorChronicleKind.interaction_close in kinds


def test_high_salience_single_turn_skips_session_resynthesis(tmp_path):
    internalizer, orch, _chronicle = _setup(tmp_path)
    internalizer.append_inbound_turn("tao", "重大消息", "回应", salience=0.7)
    unit = internalizer.close_interaction("tao")
    assert unit is None
    hot = orch._log.recent()
    assert len(hot) == 1
    assert hot[0].source == "user"


def test_outbound_open_then_inbound_turn(tmp_path):
    internalizer, orch, chronicle = _setup(tmp_path)
    internalizer.open_outbound("tao", "在吗？", reason="问候", proactive_intent_id="intent-1")
    internalizer.append_inbound_turn(
        "tao", "在的", "太好了", salience=0.35, proactive_intent_id="intent-1"
    )
    unit = internalizer.close_interaction("tao")
    assert unit is not None
    assert unit.source == "interaction"
    ctx = read_anchor_context(unit)
    assert ctx is not None
    assert ctx.direction == InteractionDirection.outbound
    assert "在吗" in unit.situation.perception
