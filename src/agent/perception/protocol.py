# -*- coding: utf-8 -*-
"""感知协议层：游戏/仿真世界 ⇄ agent.soul 之间的桥梁协议。

分层
----
1. **采集端（游戏侧）**：把世界里发生的事情以结构化事件
   （``GamePerceptionEvent``）+ 周期性现场快照（``PerceptionScene``）
   吐给协议层。采集方式不限：帧级 diff、事件打点、画面截帧。
2. **翻译端（协议层内）**：把结构化事件翻译成**流畅的自然语言**
   （``PerceptionPacket.narrative``）。当前默认实现是高成本视觉模型
   翻译器（``VisionNarrator``，多模态 LLM，可看事件附带的画面截帧），
   属于占位实现——后续会被专用的事件→叙事翻译器替换；
   ``RuleNarrator`` 是确定性离线兜底（测试/无模型环境）。
3. **接收端（soul 侧）**：自然语言包在 life 层入账
   （``GamePerceptionInbound`` → ExperienceUnit，source=game），
   成为 agent 亲历经验的一部分；speak 侧通过 life 事件口与
   ContextProvider（kind="game"）消费这些经历。

协议契约
--------
- 事件必须携带足够还原语境的 ``detail``（房间名、血量、对象名等），
  翻译器只做语言化，不负责猜测缺失事实。
- ``narrative`` 必须是流畅自然语言（完整句子），不是字段拼接。
- ``image_b64`` 可选：画面截帧（PNG base64），供视觉翻译器使用；
  无头采集端可为空，协议不强制。
- 时间统一 ISO-8601 UTC（桥侧以接收时刻打点，``frame`` 保留游戏帧号）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from agent.soul.life.experience.ingest.game import GamePerceptionInbound

PROTOCOL_VERSION = "1"
PROTOCOL_LAYER_NAME = "agent.perception"


class GameEventKind(str, Enum):
    """游戏事件种类（采集端 NDJSON ``kind`` 字段与此对齐）。"""

    game_start = "game_start"           # 一局开始
    game_clear = "game_clear"           # 通关
    chapter_begin = "chapter_begin"     # 新章节
    room_enter = "room_enter"           # 进入新区域
    player_hurt = "player_hurt"         # 旅者受伤
    player_heal = "player_heal"         # 恢复
    player_death = "player_death"       # 死亡（回到检查点）
    enemy_killed = "enemy_killed"       # 敌人被消灭
    boss_fight_start = "boss_fight_start"
    boss_defeated = "boss_defeated"
    ability_gain = "ability_gain"       # 获得新能力
    checkpoint_lit = "checkpoint_lit"   # 灯台点亮
    npc_talk = "npc_talk"               # 旅者与 NPC 交互（待 NPC 应答）
    npc_line = "npc_line"               # NPC 说了一句话（speak 产出）
    custom = "custom"                   # 采集端自定义（detail 里带 text）


# 视为"正在经历"的瞬时事件之外的持续状态（供 speak 侧 phase 标注）
_ONGOING_KINDS = frozenset({
    GameEventKind.boss_fight_start.value,
})


@dataclass(frozen=True)
class GamePerceptionEvent:
    """结构化游戏事件（采集端 → 协议层）。"""

    kind: GameEventKind
    ts: str                                  # ISO-8601 UTC
    frame: int = 0                           # 游戏帧号（可选）
    subject: str = ""                        # 事件主体（Boss 名 / NPC 名 / "旅者"）
    detail: dict[str, Any] = field(default_factory=dict)
    source: str = "game"                     # 世界标识，如 "starfall"
    image_b64: str = ""                      # 可选画面截帧（PNG base64）

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "ts": self.ts,
            "frame": self.frame,
            "subject": self.subject,
            "detail": dict(self.detail),
            "source": self.source,
            "has_image": bool(self.image_b64),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GamePerceptionEvent:
        kind = d.get("kind", "")
        try:
            parsed = GameEventKind(str(kind))
        except ValueError:
            parsed = GameEventKind.custom
            detail = dict(d.get("detail") or {})
            detail.setdefault("text", str(kind))
            d = {**d, "detail": detail}
        return cls(
            kind=parsed,
            ts=str(d.get("ts", "")),
            frame=int(d.get("frame", 0) or 0),
            subject=str(d.get("subject", "")),
            detail=dict(d.get("detail") or {}),
            source=str(d.get("source", "game")),
            image_b64=str(d.get("image_b64", "") or ""),
        )


@dataclass(frozen=True)
class PerceptionScene:
    """周期性现场快照：翻译与 speak 场景材料的共同底稿。"""

    ts: str
    room: str = ""
    room_name: str = ""
    chapter: int = 0
    player_hp: int = 0
    player_hp_max: int = 0
    deaths: int = 0
    pos_x: float = 0.0
    pos_y: float = 0.0
    enemies_alive: int = 0
    boss_active: bool = False
    abilities: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        parts: list[str] = []
        if self.room_name:
            parts.append(f"身处「{self.room_name}」")
        if self.player_hp_max:
            parts.append(f"生命 {self.player_hp}/{self.player_hp_max}")
        if self.boss_active:
            parts.append("强敌当前，战斗正在胶着")
        elif self.enemies_alive:
            parts.append(f"附近有 {self.enemies_alive} 个敌影")
        else:
            parts.append("四下寂静")
        return "，".join(parts) + "。" if parts else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "room": self.room,
            "room_name": self.room_name,
            "chapter": self.chapter,
            "player_hp": self.player_hp,
            "player_hp_max": self.player_hp_max,
            "deaths": self.deaths,
            "pos_x": self.pos_x,
            "pos_y": self.pos_y,
            "enemies_alive": self.enemies_alive,
            "boss_active": self.boss_active,
            "abilities": list(self.abilities),
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PerceptionScene:
        return cls(
            ts=str(d.get("ts", "")),
            room=str(d.get("room", "")),
            room_name=str(d.get("room_name", "")),
            chapter=int(d.get("chapter", 0) or 0),
            player_hp=int(d.get("player_hp", 0) or 0),
            player_hp_max=int(d.get("player_hp_max", 0) or 0),
            deaths=int(d.get("deaths", 0) or 0),
            pos_x=float(d.get("pos_x", 0.0) or 0.0),
            pos_y=float(d.get("pos_y", 0.0) or 0.0),
            enemies_alive=int(d.get("enemies_alive", 0) or 0),
            boss_active=bool(d.get("boss_active", False)),
            abilities=tuple(str(a) for a in (d.get("abilities") or [])),
            extra=dict(d.get("extra") or {}),
        )


@dataclass(frozen=True)
class PerceptionPacket:
    """自然语言感知包（协议层的最终产物，soul 只认这个）。"""

    event: GamePerceptionEvent
    narrative: str                           # 流畅自然语言事件描述
    salience: float = 0.4
    emotion_label: str = ""
    valence_delta: float = 0.0
    arousal_delta: float = 0.0
    scene_text: str = ""                     # 事件发生时的现场摘要
    translator: str = "rule"                 # 产出该包的翻译器标识
    protocol_version: str = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if not self.narrative.strip():
            raise ValueError("PerceptionPacket.narrative 不能为空")

    @property
    def ongoing(self) -> bool:
        return self.event.kind.value in _ONGOING_KINDS

    def to_beat(
        self,
        *,
        session_id: str = "tao",
        channel_id: str = "",
    ) -> GamePerceptionInbound:
        """→ life 层入站包（experience unit，source=game）。"""
        return GamePerceptionInbound(
            narrative=self.narrative.strip(),
            session_id=session_id,
            channel_id=channel_id,
            emotion_label=self.emotion_label,
            valence_delta=self.valence_delta,
            arousal_delta=self.arousal_delta,
            salience=self.salience,
            trigger=f"game:{self.event.kind.value}",
            scene=self.scene_text,
            evidence={
                "protocol_version": self.protocol_version,
                "translator": self.translator,
                "game_event": self.event.to_dict(),
            },
        )


@runtime_checkable
class PerceptionTranslator(Protocol):
    """事件 → 自然语言翻译器协议。

    实现要求：线程安全；单事件失败应抛出或返回 None（由总线兜底），
    不允许返回空字符串。
    """

    @property
    def name(self) -> str: ...

    def translate(
        self,
        event: GamePerceptionEvent,
        scene: PerceptionScene | None = None,
    ) -> PerceptionPacket: ...
