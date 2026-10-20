# -*- coding: utf-8 -*-
"""感知协议层（agent.perception）：游戏/仿真世界 ⇄ agent.soul 的桥梁。

- ``protocol``  事件/现场/自然语言包契约 + 翻译器协议
- ``narrate``   规则叙事器（确定性离线兜底）
- ``vision``    高成本视觉模型翻译器（当前默认占位实现）
- ``bus``       感知总线：翻译 → 存储 → life 入账 → 订阅者
- ``store``     近期包存储（speak 侧唯一读模型）
- ``speak_provider`` ContextProvider(kind="game")，注册进 SpeakService
- ``gamebridge`` 具体游戏桥（首个：类银河恶魔城 demo《星陨之痕》）
- ``runtime``   进程内嵌装配（lite 离线 / full SoulService 两种）
"""

from agent.perception.bus import PerceptionBus
from agent.perception.narrate import RuleNarrator
from agent.perception.protocol import (
    PROTOCOL_VERSION,
    GameEventKind,
    GamePerceptionEvent,
    PerceptionPacket,
    PerceptionScene,
    PerceptionTranslator,
)
from agent.perception.speak_provider import GameContextProvider
from agent.perception.store import RecentPacketStore

__all__ = [
    "PROTOCOL_VERSION",
    "GameContextProvider",
    "GameEventKind",
    "GamePerceptionEvent",
    "PerceptionBus",
    "PerceptionPacket",
    "PerceptionScene",
    "PerceptionTranslator",
    "RecentPacketStore",
    "RuleNarrator",
]
