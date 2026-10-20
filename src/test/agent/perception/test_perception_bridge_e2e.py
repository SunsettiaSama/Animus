from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.perception.gamebridge import MetroidvaniaBridge, NpcDialogueBridge
from agent.perception.gamebridge.metroidvania import demo_available, node_available
from agent.perception.runtime import build_lite_runtime, drive_bridge
from agent.soul.life.virtual.chronicle import VirtualChronicleStore

pytestmark = pytest.mark.skipif(
    not (node_available() and demo_available()),
    reason="需要 Node.js 与 demos/metroidvania 无头 harness",
)


def test_starfall_e2e_game_to_soul_pipeline(tmp_path):
    """无头跑通整局：游戏事件 → 自然语言 → life 入账 → NPC 对话回注。"""
    life_dir = str(tmp_path)
    runtime = build_lite_runtime(life_dir)
    npc_bridge = NpcDialogueBridge(
        runtime.speak_turn,
        npc_name=runtime.npc_name,
        session_id=runtime.session_id,
        channel_id=runtime.channel_id,
    )
    bridge = MetroidvaniaBridge(scenario="story")
    try:
        summary = drive_bridge(bridge=bridge, bus=runtime.bus, npc_bridge=npc_bridge)
    finally:
        bridge.stop()

    # 采集端：完整事件谱系、零错误
    assert summary.errors == 0
    for kind in ("game_start", "room_enter", "checkpoint_lit", "player_hurt",
                 "enemy_killed", "ability_gain", "boss_fight_start", "boss_defeated",
                 "chapter_begin", "game_clear", "npc_talk"):
        assert summary.events.get(kind, 0) >= 1, f"缺少事件 {kind}"

    # NPC：speak 台词已生成并回注
    assert summary.npc_lines, "NPC 应至少产生一句台词"

    # life：游戏亲历成为经验（source=game）并落虚拟账本
    units = runtime.stack.log.recent()
    game_units = [u for u in units if u.source == "game"]
    assert game_units
    assert all(u.situation.narration for u in game_units)  # 全是自然语言叙事

    entries = VirtualChronicleStore(life_dir).recent_days(days=1)
    game_entries = [e for e in entries if e.kind.value == "game_event"]
    assert game_entries

    # speak 侧：游戏事件可被角色读到（life 事件口）
    assert runtime.bus.game_event_briefs()

    # NPC 对话以 dialogue 经验落账
    closed = runtime.stack.close_dialogue(runtime.session_id)
    assert closed is not None
