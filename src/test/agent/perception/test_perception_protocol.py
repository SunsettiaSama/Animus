from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.perception.protocol import (
    PROTOCOL_VERSION,
    GameEventKind,
    GamePerceptionEvent,
    PerceptionPacket,
    PerceptionScene,
)
from agent.soul.life.experience.ingest.game import GamePerceptionInbound


def _event(kind: str = "boss_defeated", **detail) -> GamePerceptionEvent:
    return GamePerceptionEvent.from_dict({
        "kind": kind,
        "ts": "2026-09-21T00:00:00+00:00",
        "frame": 42,
        "detail": detail or {"boss_name": "矿洞魔像"},
        "source": "starfall",
    })


def test_event_from_dict_maps_known_kind():
    event = _event()
    assert event.kind is GameEventKind.boss_defeated
    assert event.frame == 42
    assert event.detail["boss_name"] == "矿洞魔像"
    assert event.to_dict()["kind"] == "boss_defeated"


def test_event_from_dict_unknown_kind_falls_back_to_custom():
    event = _event("奇怪的震动")
    assert event.kind is GameEventKind.custom
    assert event.detail["text"] == "奇怪的震动"


def test_scene_summary_is_fluent_chinese():
    scene = PerceptionScene.from_dict({
        "ts": "2026-09-21T00:00:00+00:00",
        "room": "c1_1",
        "room_name": "幽暗矿脉 · 入口",
        "player_hp": 4,
        "player_hp_max": 5,
        "enemies_alive": 2,
    })
    text = scene.summary()
    assert "幽暗矿脉 · 入口" in text
    assert "4/5" in text
    assert text.endswith("。")


def test_packet_requires_narrative():
    import pytest

    with pytest.raises(ValueError):
        PerceptionPacket(event=_event(), narrative="   ")


def test_packet_to_beat_carries_protocol_evidence():
    packet = PerceptionPacket(
        event=_event(),
        narrative="「矿洞魔像」轰然倒地，封印开启。",
        salience=0.85,
        emotion_label="激动",
        valence_delta=0.5,
    )
    beat = packet.to_beat(session_id="starfall-npc", channel_id="starfall")
    assert isinstance(beat, GamePerceptionInbound)
    assert beat.narrative == "「矿洞魔像」轰然倒地，封印开启。"
    assert beat.session_id == "starfall-npc"
    assert beat.channel_id == "starfall"
    assert beat.salience == 0.85
    assert beat.trigger == "game:boss_defeated"
    assert beat.evidence["protocol_version"] == PROTOCOL_VERSION
    assert beat.evidence["game_event"]["kind"] == "boss_defeated"


def test_beat_rejects_empty_narrative():
    import pytest

    with pytest.raises(ValueError):
        GamePerceptionInbound(narrative="  ")


def test_boss_fight_is_ongoing_for_speak_phase():
    packet = PerceptionPacket(event=_event("boss_fight_start"), narrative="大地开始震动。")
    assert packet.ongoing is True
    calm = PerceptionPacket(event=_event("room_enter", room_name="回声竖井"), narrative="旅者走进了「回声竖井」。")
    assert calm.ongoing is False
