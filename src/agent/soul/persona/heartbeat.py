# -*- coding: utf-8 -*-
"""persona 域心跳入口：月度人格漂移（self_concept 演化的唯一入口）。"""

from __future__ import annotations

from typing import Any

from agent.soul.heartbeat.schedule.context import HeartbeatContext
from agent.soul.heartbeat.schedule.item import ChecklistItem, ChecklistTrigger
from agent.soul.handlers.api.actions import PersonaAction


def wake_items(cfg) -> list[ChecklistItem]:
    c = cfg or _fallback_cfg()
    return [
        ChecklistItem(
            id="persona-monthly-drift",
            domain="persona",
            action=PersonaAction.RUN_MONTHLY_DRIFT,
            trigger=ChecklistTrigger.monthly,
            monthly_day=c.persona_drift_day_of_month,
            monthly_at=c.persona_drift_at,
            target="agent.soul.persona.heartbeat:monthly_drift_entry",
            heavy=True,
            enabled=True,
        ),
    ]


def _fallback_cfg():
    from config.soul.config import SoulConfig

    return SoulConfig.default()


def monthly_drift_entry(payload: dict, ctx: HeartbeatContext) -> Any:
    from agent.soul.request import SoulChannel, SoulDomain, SoulRequest

    return ctx.soul.dispatch(SoulRequest(
        domain=SoulDomain.persona,
        action=PersonaAction.RUN_MONTHLY_DRIFT,
        payload=dict(payload),
        channel=SoulChannel.api,
    ))
