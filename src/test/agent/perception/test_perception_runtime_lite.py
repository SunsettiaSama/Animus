from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.perception.protocol import GameEventKind, GamePerceptionEvent, PerceptionScene
from agent.perception.bus import utc_now_iso
from agent.perception.runtime import build_lite_runtime


def test_lite_runtime_speak_turn_returns_npc_line(tmp_path):
    runtime = build_lite_runtime(tmp_path)
    answer = runtime.speak_turn(runtime.session_id, "（一位旅者停下了脚步，想和你说话。）")
    assert answer.strip()
    assert "[" not in answer and "<" not in answer  # 纯文本台词


def test_lite_runtime_npc_dialogue_lands_in_life(tmp_path):
    runtime = build_lite_runtime(tmp_path)
    # 世界先有事件（游戏亲历持续给 presence 供内容），NPC 对话发生在世界之中
    runtime.bus.publish_event(GamePerceptionEvent(
        kind=GameEventKind.checkpoint_lit,
        ts=utc_now_iso(),
        detail={"room": "c1_1"},
    ))
    runtime.speak_turn(runtime.session_id, "（一位旅者停下了脚步，想和你说话。）")
    runtime.speak_turn(runtime.session_id, "旅者问道：前面的矿道深吗？")
    closed = runtime.stack.close_dialogue(runtime.session_id)
    assert closed is not None
    assert closed.source in ("user", "interaction")
    assert any(u.id == closed.id for u in runtime.stack.log.recent())


def test_lite_runtime_bus_ingests_game_events(tmp_path):
    runtime = build_lite_runtime(tmp_path)
    packet = runtime.bus.publish_event(GamePerceptionEvent(
        kind=GameEventKind.boss_defeated,
        ts=utc_now_iso(),
        detail={"boss_name": "矿洞魔像"},
    ))
    assert packet.narrative
    units = runtime.stack.log.recent()
    assert any(u.source == "game" and "矿洞魔像" in u.situation.narration for u in units)


def test_lite_runtime_registers_game_context_provider(tmp_path):
    runtime = build_lite_runtime(tmp_path)
    kinds = runtime.speak.context_provider_kinds()
    assert "game" in kinds
    runtime.bus.publish_event(GamePerceptionEvent(
        kind=GameEventKind.room_enter,
        ts=utc_now_iso(),
        detail={"room_name": "回声竖井"},
    ), PerceptionScene(
        ts=utc_now_iso(),
        room="c1_2",
        room_name="回声竖井",
        player_hp=5,
        player_hp_max=5,
    ))
    registry = runtime.speak._context_providers
    provider = next(p for p in registry._providers if p.kind == "game")
    snap = provider.snapshot("starfall-npc")
    assert "回声竖井" in snap["scene_event"]


def test_lite_runtime_life_event_port_sees_game_briefs(tmp_path):
    runtime = build_lite_runtime(tmp_path)
    runtime.bus.publish_event(GamePerceptionEvent(
        kind=GameEventKind.player_death,
        ts=utc_now_iso(),
        detail={"deaths": 1},
    ))
    state = runtime.speak._life_event_state()
    assert state["events"]
    assert state["everyday"] is False
    assert any("旅者" in line for line in state["events"])
