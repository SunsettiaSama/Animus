from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.soul.life.experience import LifeExperienceStack
from agent.soul.life.experience.ingest.game import GamePerceptionInbound
from agent.soul.life.virtual.chronicle import VirtualChronicleStore
from agent.soul.presence.service import PresenceService


def _stack(tmp_path):
    life_dir = str(tmp_path)
    presence = PresenceService(life_dir=life_dir)
    stack = LifeExperienceStack(life_dir, virtual_chronicle=VirtualChronicleStore(life_dir))
    stack.bind_presence(presence)
    return stack, presence


def test_ingest_game_beat_creates_game_source_unit(tmp_path):
    stack, _ = _stack(tmp_path)
    unit = stack.ingest_game_beat(GamePerceptionInbound(
        narrative="「矿洞魔像」轰然倒地，封印开启。",
        session_id="starfall-npc",
        channel_id="starfall",
        salience=0.85,
        emotion_label="激动",
        valence_delta=0.5,
        trigger="game:boss_defeated",
        scene="身处「魔像巢穴」，生命 5/5。",
        evidence={"protocol_version": "1"},
    ))

    assert unit.source == "game"
    assert unit.situation.narration == "「矿洞魔像」轰然倒地，封印开启。"
    assert unit.feeling.salience == 0.85
    assert unit.situation.session_id == "starfall-npc"
    assert unit.evidence["perception_protocol"]["trigger"] == "game:boss_defeated"
    assert unit.evidence["protocol_version"] == "1"

    hot = stack.log.recent()
    assert any(u.source == "game" for u in hot)


def test_ingest_game_beat_routes_to_virtual_chronicle(tmp_path):
    stack, _ = _stack(tmp_path)
    stack.ingest_game_beat(GamePerceptionInbound(
        narrative="一盏灯台被点亮了，火光稳稳地立在那里。",
        salience=0.5,
    ))

    entries = VirtualChronicleStore(str(tmp_path)).recent_days(days=1)
    game_entries = [e for e in entries if e.kind.value == "game_event"]
    assert len(game_entries) == 1
    assert "灯台" in game_entries[0].summary
    assert game_entries[0].salience == 0.5


def test_game_source_routed_as_virtual(tmp_path):
    from agent.soul.life.experience.domain.sources import is_virtual_source

    assert is_virtual_source("game") is True
    assert is_virtual_source("narrative") is True


def test_ingest_game_beat_syncs_presence(tmp_path):
    stack, presence = _stack(tmp_path)
    stack.ingest_game_beat(GamePerceptionInbound(
        narrative="旅者走进了「摘星之塔」。",
        session_id="starfall-npc",
        salience=0.3,
    ))
    snap = presence.snapshot("starfall-npc")
    text = snap.state.perception.narrative or snap.state.cognition.thinking
    assert text  # presence 已知晓游戏亲历（narration/thinking 至少其一非空）
