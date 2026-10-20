# -*- coding: utf-8 -*-
"""NPC 对话桥：游戏交互 → soul speak 回合 → 台词回注游戏。

NPC 即 soul 在游戏世界中的化身（守灯人·烛）。旅者靠近按键 =
一次 speak 入站回合；游戏亲历事件已作为 life 经验在场，
speak 的编剧材料会自然织入（life 事件口 + ContextProvider）。
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

logger = logging.getLogger(__name__)

# speak 侧输出可能残留 [speak]/<speak>/[state] 等标签；NPC 台词取纯文本
_TAG_RE = re.compile(
    r"\[(?:speak|action|state|think|observe)[^\]]*\]|\[/speak\]|\[/action\]"
    r"|</?speak>|</?action>|</?think>",
    re.IGNORECASE,
)


def strip_speak_tags(text: str) -> str:
    return _TAG_RE.sub("", text).strip()


class NpcDialogueBridge:
    """npc_talk 事件 → speak_run_turn → 台词回注。"""

    def __init__(
        self,
        speak_turn: Callable[[str, str], str],
        *,
        npc_name: str = "守灯人",
        session_id: str = "starfall-npc",
        channel_id: str = "starfall",
    ) -> None:
        self._speak_turn = speak_turn
        self.npc_name = npc_name
        self.session_id = session_id
        self.channel_id = channel_id

    def player_greeting(self, detail: dict) -> str:
        """旅者交互 → speak 侧的用户文本（以 NPC 视角描述来客）。"""
        room = str(detail.get("room_name", "")).strip()
        where = f"，就在{room}" if room else ""
        return f"（一位旅者走到你面前停下了脚步{where}，看样子想和你说话。）"

    def handle_talk(self, detail: dict) -> str | None:
        """处理 npc_talk 事件；返回台词（失败返回 None，由调用方决定兜底）。"""
        try:
            raw = self._speak_turn(self.session_id, self.player_greeting(detail))
        except Exception as exc:  # noqa: BLE001 — speak 抖动不能卡死游戏
            logger.warning("[NPC桥] speak 回合失败：%s", exc)
            return None
        line = strip_speak_tags(str(raw))
        return line or None

    def reactive_remark(self, packet) -> str | None:
        """大事件触发的主动一句（如强敌倒下）；复用 speak 回合。"""
        cue = f"（你刚亲历：{packet.narrative.strip()}）你对此有一句想说的话，说吧。"
        try:
            raw = self._speak_turn(self.session_id, cue)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[NPC桥] 主动发言失败：%s", exc)
            return None
        return strip_speak_tags(str(raw)) or None
