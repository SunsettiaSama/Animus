# -*- coding: utf-8 -*-
"""心跳注册装配：汇集各域 wake_items 注册进 checklist。

heartbeat 零模块知识——知识住各域（memory/life/presence/persona/wiring-story），
本文件是唯一的汇集点（wake-registration-prd §3）。
"""

from __future__ import annotations


def register_default_wake_items(module, soul) -> int:
    """注册默认唤醒项；checklist 已有项时不覆盖（外部 bind 可能自带）。"""
    checklist = module.orchestrator.checklist
    if checklist.all():
        return 0

    from agent.soul.life.heartbeat import wake_items as life_items
    from agent.soul.memory.heartbeat import wake_items as memory_items
    from agent.soul.persona.heartbeat import wake_items as persona_items
    from agent.soul.presence.heartbeat import wake_items as presence_items
    from agent.soul.wiring.story_tick import story_wake_items
    from runtime.scheduler.heartbeat import wake_items as scheduler_items

    cfg = soul.config
    items = [
        *life_items(cfg),
        *story_wake_items(),
        *memory_items(cfg),
        *presence_items(cfg),
        *persona_items(cfg),
        *scheduler_items(),
    ]
    checklist.register_all(items)
    return len(items)
