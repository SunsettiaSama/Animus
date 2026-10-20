from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[3]
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.perception.bus import PerceptionBus, utc_now_iso
from agent.perception.protocol import GameEventKind, GamePerceptionEvent, PerceptionScene
from agent.perception.speak_provider import GameContextProvider
from agent.perception.store import RecentPacketStore


def _event(kind: GameEventKind = GameEventKind.room_enter, **detail) -> GamePerceptionEvent:
    return GamePerceptionEvent(
        kind=kind,
        ts=utc_now_iso(),
        detail=detail or {"room_name": "回声竖井"},
    )


def test_bus_publishes_to_store_subscriber_and_life_sink():
    seen_packets = []
    sunk = []
    bus = PerceptionBus(life_sink=sunk.append)
    bus.subscribe(seen_packets.append)

    packet = bus.publish_event(_event())

    assert packet.narrative
    assert seen_packets == [packet]
    assert sunk == [packet]
    briefs = bus.game_event_briefs()
    assert len(briefs) == 1
    brief = briefs[0]
    # speak life 事件口契约
    assert brief["intention"]
    assert brief["phase"] in ("experiencing", "just_done", "due")
    assert brief["narrative"] == packet.narrative
    assert brief["scheduled_at"]


def test_bus_survives_life_sink_failure():
    def bad_sink(packet):
        raise RuntimeError("life down")

    bus = PerceptionBus(life_sink=bad_sink)
    packet = bus.publish_event(_event())
    assert packet.narrative
    assert bus.game_event_briefs()  # 事件保留在存储中


def test_bus_survives_broken_translator():
    class _Broken:
        @property
        def name(self) -> str:
            return "broken"

        def translate(self, event, scene=None):
            raise RuntimeError("translator boom")

    bus = PerceptionBus(_Broken())
    packet = bus.publish_event(_event())
    assert "回声竖井" in packet.narrative  # 规则兜底


def test_bus_fills_missing_timestamp():
    event = GamePerceptionEvent(kind=GameEventKind.game_start, ts="")
    packet = PerceptionBus().publish_event(event)
    assert packet.event.ts  # 总线以接收时刻打点


def test_store_briefs_phase_marks_ongoing_fights():
    store = RecentPacketStore()
    from agent.perception.protocol import PerceptionPacket

    for kind in (GameEventKind.boss_fight_start, GameEventKind.player_hurt):
        event = GamePerceptionEvent(kind=kind, ts=utc_now_iso())
        store.record_packet(PerceptionPacket(event=event, narrative=f"{kind.value} 叙事"))
    briefs = store.briefs()   # 最新在前
    assert briefs[0]["phase"] == "just_done"       # player_hurt（普通事件）
    assert briefs[1]["phase"] == "experiencing"    # boss 战进行中


def test_game_context_provider_snapshot_shape():
    store = RecentPacketStore()
    bus = PerceptionBus(store=store)
    scene = PerceptionScene(
        ts=utc_now_iso(),
        room="c1_3",
        room_name="魔像巢穴",
        player_hp=5,
        player_hp_max=5,
        boss_active=True,
    )
    bus.publish_event(_event(GameEventKind.boss_fight_start, boss_name="矿洞魔像"), scene)

    provider = GameContextProvider(store, world_name="星陨之痕")
    assert provider.kind == "game"
    snap = provider.snapshot("starfall-npc")
    # ContextProvider 契约字段
    assert snap["kind"] == "game"
    assert snap["material_schedule"] == {}          # 不提案调度，编剧主导
    assert "魔像巢穴" in snap["scene_event"] and "星陨之痕" in snap["scene_event"]
    assert "苏醒" in snap["plot_flow_text"]
