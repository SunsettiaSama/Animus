# -*- coding: utf-8 -*-
"""近期感知包存储：speak 侧消费（life 事件简报 / 场景材料）的唯一读模型。"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone

from agent.perception.protocol import PerceptionPacket, PerceptionScene

_KIND_LABELS = {
    "game_start": "旅程开始",
    "game_clear": "星门开启",
    "chapter_begin": "新篇章",
    "room_enter": "行至新域",
    "player_hurt": "旅者受创",
    "player_heal": "伤口愈合",
    "player_death": "旅者殒落",
    "enemy_killed": "敌影消散",
    "boss_fight_start": "强敌苏醒",
    "boss_defeated": "强敌倒下",
    "ability_gain": "获赠之物",
    "checkpoint_lit": "灯台点亮",
    "npc_talk": "旅者驻足",
    "npc_line": "守灯人开口",
    "custom": "世界涟漪",
}


def _parse_ts(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass(frozen=True)
class StoredPacket:
    ts: str
    kind: str
    narrative: str
    salience: float
    ongoing: bool


class RecentPacketStore:
    """线程安全的近期包缓存（桥线程写 / speak 线程读）。"""

    def __init__(self, *, capacity: int = 64) -> None:
        self._lock = threading.Lock()
        self._packets: deque[StoredPacket] = deque(maxlen=capacity)
        self._scene: PerceptionScene | None = None

    def record_packet(self, packet: PerceptionPacket) -> None:
        item = StoredPacket(
            ts=packet.event.ts,
            kind=packet.event.kind.value,
            narrative=packet.narrative.strip(),
            salience=float(packet.salience),
            ongoing=bool(packet.ongoing),
        )
        if not item.narrative:
            return
        with self._lock:
            self._packets.append(item)

    def record_scene(self, scene: PerceptionScene) -> None:
        with self._lock:
            self._scene = scene

    def latest_scene(self) -> PerceptionScene | None:
        with self._lock:
            return self._scene

    def recent_packets(self, *, limit: int = 4, within_sec: float = 3600.0) -> list[StoredPacket]:
        now = datetime.now(timezone.utc)
        with self._lock:
            items = list(self._packets)
        out: list[StoredPacket] = []
        for item in reversed(items):
            if (now - _parse_ts(item.ts)).total_seconds() > within_sec:
                continue
            out.append(item)
            if len(out) >= max(0, limit):
                break
        return out

    def briefs(self, *, within_sec: float = 3600.0, limit: int = 3) -> list[dict]:
        """speak life 事件口形状：[{intention, phase, narrative, scheduled_at, context}]。"""
        out: list[dict] = []
        for item in self.recent_packets(limit=limit, within_sec=within_sec):
            label = _KIND_LABELS.get(item.kind, "世界涟漪")
            out.append({
                "id": f"game:{item.kind}:{item.ts}",
                "intention": f"游戏亲历·{label}",
                "narrative": item.narrative[:160],
                "phase": "experiencing" if item.ongoing else "just_done",
                "scheduled_at": item.ts,
                "context": "感知协议层：游戏世界真实发生",
            })
        return out
