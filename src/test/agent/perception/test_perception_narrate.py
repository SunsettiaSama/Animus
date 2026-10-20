from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.perception.narrate import RuleNarrator
from agent.perception.protocol import GamePerceptionEvent, PerceptionScene


def _narrator() -> RuleNarrator:
    return RuleNarrator()


def _scene() -> PerceptionScene:
    return PerceptionScene(
        ts="2026-09-21T00:00:00+00:00",
        room="c1_3",
        room_name="魔像巢穴",
        chapter=1,
        player_hp=5,
        player_hp_max=5,
    )


def test_boss_defeated_fluent_sentence():
    packet = _narrator().translate(GamePerceptionEvent.from_dict({
        "kind": "boss_defeated",
        "ts": "2026-09-21T00:00:00+00:00",
        "detail": {"boss_name": "矿洞魔像"},
    }), _scene())
    assert "矿洞魔像" in packet.narrative
    assert packet.narrative.endswith("。")
    assert packet.salience >= 0.8
    assert packet.emotion_label


def test_player_hurt_carries_hp_detail():
    packet = _narrator().translate(GamePerceptionEvent.from_dict({
        "kind": "player_hurt",
        "ts": "2026-09-21T00:00:00+00:00",
        "detail": {"hp": 2, "hp_max": 5, "cause": "地刺"},
    }))
    assert "受了伤" in packet.narrative
    assert "2/5" in packet.narrative
    assert "地刺" in packet.narrative
    assert packet.valence_delta < 0


def test_death_counts_total():
    packet = _narrator().translate(GamePerceptionEvent.from_dict({
        "kind": "player_death",
        "ts": "2026-09-21T00:00:00+00:00",
        "detail": {"deaths": 3},
    }))
    assert "倒下" in packet.narrative
    assert "第 3 次" in packet.narrative


def test_room_enter_uses_room_name():
    packet = _narrator().translate(GamePerceptionEvent.from_dict({
        "kind": "room_enter",
        "ts": "2026-09-21T00:00:00+00:00",
        "detail": {"room_name": "摘星之塔"},
    }))
    assert "摘星之塔" in packet.narrative
    assert packet.scene_text == ""  # 未给 scene 时不编造现场


def test_custom_event_prefers_text_detail():
    packet = _narrator().translate(GamePerceptionEvent.from_dict({
        "kind": "custom",
        "ts": "2026-09-21T00:00:00+00:00",
        "detail": {"text": "远处传来钟声。"},
    }))
    assert packet.narrative == "远处传来钟声。"


def test_ability_gain_maps_item_name():
    packet = _narrator().translate(GamePerceptionEvent.from_dict({
        "kind": "ability_gain",
        "ts": "2026-09-21T00:00:00+00:00",
        "detail": {"ability": "dj"},
    }))
    assert "星羽" in packet.narrative


def test_scene_text_attached_when_scene_given():
    packet = _narrator().translate(GamePerceptionEvent.from_dict({
        "kind": "checkpoint_lit",
        "ts": "2026-09-21T00:00:00+00:00",
        "detail": {"room": "c1_1"},
    }), _scene())
    assert "魔像巢穴" in packet.scene_text
