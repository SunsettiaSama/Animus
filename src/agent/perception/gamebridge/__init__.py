# -*- coding: utf-8 -*-
"""游戏桥：具体游戏 ↔ 感知协议层的采集端对接（首个：类银河恶魔城《星陨之痕》）。"""

from agent.perception.gamebridge.metroidvania import MetroidvaniaBridge
from agent.perception.gamebridge.npc import NpcDialogueBridge

__all__ = ["MetroidvaniaBridge", "NpcDialogueBridge"]
