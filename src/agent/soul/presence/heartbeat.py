# -*- coding: utf-8 -*-
"""presence 域心跳入口：唤醒 / 期望扫描 / 外部机会扫描的注册项与实现。"""

from __future__ import annotations

from typing import Any

from agent.soul.heartbeat.schedule.context import HeartbeatContext
from agent.soul.heartbeat.schedule.item import ChecklistItem, ChecklistTrigger
from agent.soul.presence.actions import PresenceAction


def wake_items(cfg) -> list[ChecklistItem]:
    _ = cfg
    return [
        ChecklistItem(
            id="presence-wake-up",
            domain="presence",
            action=PresenceAction.WAKE_UP,
            trigger=ChecklistTrigger.daily,
            daily_at=_presence_wake_at(cfg),
            target="agent.soul.presence.heartbeat:presence_wake_entry",
        ),
        ChecklistItem(
            id="presence-expectation-scan",
            domain="presence",
            action=PresenceAction.SCAN_EXPECTATION,
            trigger=ChecklistTrigger.interval,
            interval_sec=300.0,
            payload={"session_id": "tao"},
            target="agent.soul.presence.heartbeat:scan_expectation_entry",
        ),
        ChecklistItem(
            id="presence-external-scan",
            domain="presence",
            action=PresenceAction.SCAN_EXTERNAL,
            trigger=ChecklistTrigger.interval,
            interval_sec=900.0,
            payload={"session_id": "tao"},
            target="agent.soul.presence.heartbeat:scan_external_entry",
        ),
    ]


def _presence_wake_at(cfg) -> str:
    at = getattr(cfg, "presence_wake_at", None) if cfg is not None else None
    return str(at) if at else "08:00"


def presence_wake_entry(payload: dict, ctx: HeartbeatContext) -> dict[str, Any]:
    session_id = str(payload.get("session_id", "tao"))
    return ctx.soul.run_presence_wake(session_id=session_id)


def scan_expectation_entry(payload: dict, ctx: HeartbeatContext) -> dict[str, Any]:
    session_id = str(payload.get("session_id", "tao"))
    return ctx.soul.run_expectation_scan(session_id=session_id)


def scan_external_entry(payload: dict, ctx: HeartbeatContext) -> dict[str, Any]:
    session_id = str(payload.get("session_id", "tao"))
    return ctx.soul.run_external_opportunity_scan(session_id=session_id)
