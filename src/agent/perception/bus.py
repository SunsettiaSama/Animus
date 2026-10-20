# -*- coding: utf-8 -*-
"""感知总线：结构化事件 → 翻译 → 自然语言包 → life 入账 + 订阅者广播。

故障隔离约定：翻译端失败回退规则叙事；life 写入失败只记日志，
绝不让游戏侧桥因 soul 侧抖动而断流。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from agent.perception.narrate import RuleNarrator
from agent.perception.protocol import (
    GamePerceptionEvent,
    PerceptionPacket,
    PerceptionScene,
    PerceptionTranslator,
)
from agent.perception.store import RecentPacketStore

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PerceptionBus:
    """事件发布中枢（采集端唯一需要对接的对象）。"""

    def __init__(
        self,
        translator: PerceptionTranslator | None = None,
        *,
        life_sink: Callable[[PerceptionPacket], Any] | None = None,
        store: RecentPacketStore | None = None,
    ) -> None:
        self._translator = translator or RuleNarrator()
        self._fallback = RuleNarrator()
        self._life_sink = life_sink
        self.store = store or RecentPacketStore()
        self._subscribers: list[Callable[[PerceptionPacket], Any]] = []

    @property
    def translator(self) -> PerceptionTranslator:
        return self._translator

    def subscribe(self, fn: Callable[[PerceptionPacket], Any]) -> None:
        self._subscribers.append(fn)

    def bind_life_sink(self, sink: Callable[[PerceptionPacket], Any] | None) -> None:
        """重绑 life 写入口（full-soul 装配时把写入切到 SoulService）。"""
        self._life_sink = sink

    # ── 发布 ────────────────────────────────────────────────────────────────

    def publish_event(
        self,
        event: GamePerceptionEvent,
        scene: PerceptionScene | None = None,
    ) -> PerceptionPacket:
        """单个事件全链路：翻译 → 存储 → 订阅者 → life 入账。"""
        if not event.ts:
            event = replace(event, ts=utc_now_iso())
        packet = self._translate(event, scene)
        self.store.record_packet(packet)
        if scene is not None:
            self.store.record_scene(scene)
        for fn in self._subscribers:
            try:
                fn(packet)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[感知协议层] 订阅者异常（已忽略）：%s", exc)
        if self._life_sink is not None:
            try:
                self._life_sink(packet)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[感知协议层] life 写入失败（事件保留在存储中）：%s", exc)
        return packet

    def publish_scene(self, scene: PerceptionScene) -> None:
        self.store.record_scene(scene)

    # ── speak 侧读口 ─────────────────────────────────────────────────────────

    def game_event_briefs(self) -> list[dict]:
        """speak life 事件口（attach_life_event_port 形状）。"""
        return self.store.briefs(within_sec=3600.0, limit=3)

    # ── 内部 ─────────────────────────────────────────────────────────────────

    def _translate(self, event: GamePerceptionEvent, scene: PerceptionScene | None) -> PerceptionPacket:
        try:
            packet = self._translator.translate(event, scene)
            if packet.narrative.strip():
                return packet
        except Exception as exc:  # noqa: BLE001
            logger.warning("[感知协议层] 翻译器 %s 异常，回退规则叙事：%s", self._translator.name, exc)
        return self._fallback.translate(event, scene)
