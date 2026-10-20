# -*- coding: utf-8 -*-
"""确定性规则翻译器：结构化游戏事件 → 流畅自然语言。

这是协议的离线兜底实现（无 LLM 环境/单测/视觉模型失败回退）。
正式线上走 ``VisionNarrator``（高成本视觉模型占位翻译器），
未来替换为专用事件→叙事翻译器时，本类仍保留为降级路径。
"""

from __future__ import annotations

from agent.perception.protocol import (
    GameEventKind,
    GamePerceptionEvent,
    PerceptionPacket,
    PerceptionScene,
)

# 事件 → (基准 salience, 情绪标签, valence, arousal)
_KIND_FEELING: dict[GameEventKind, tuple[float, str, float, float]] = {
    GameEventKind.game_start: (0.60, "期待", 0.20, 0.30),
    GameEventKind.game_clear: (0.90, "震动", 0.60, 0.50),
    GameEventKind.chapter_begin: (0.55, "郑重", 0.10, 0.20),
    GameEventKind.room_enter: (0.30, "平静", 0.00, 0.05),
    GameEventKind.player_hurt: (0.45, "揪心", -0.30, 0.30),
    GameEventKind.player_heal: (0.25, "宽慰", 0.25, 0.00),
    GameEventKind.player_death: (0.80, "哀恸", -0.60, 0.40),
    GameEventKind.enemy_killed: (0.35, "专注", 0.05, 0.20),
    GameEventKind.boss_fight_start: (0.70, "紧张", -0.10, 0.50),
    GameEventKind.boss_defeated: (0.85, "激动", 0.55, 0.50),
    GameEventKind.ability_gain: (0.60, "欣喜", 0.40, 0.30),
    GameEventKind.checkpoint_lit: (0.50, "安宁", 0.30, 0.00),
    GameEventKind.npc_talk: (0.50, "注视", 0.10, 0.10),
    GameEventKind.npc_line: (0.40, "表达", 0.10, 0.00),
    GameEventKind.custom: (0.40, "留意", 0.00, 0.10),
}

_ABILITY_NAMES = {"dash": "疾行之靴", "dj": "星羽"}


class RuleNarrator:
    """规则模板翻译（确定性，零依赖）。"""

    def __init__(self) -> None:
        pass

    @property
    def name(self) -> str:
        return "rule"

    def translate(
        self,
        event: GamePerceptionEvent,
        scene: PerceptionScene | None = None,
    ) -> PerceptionPacket:
        salience, emotion, valence, arousal = _KIND_FEELING.get(
            event.kind, _KIND_FEELING[GameEventKind.custom]
        )
        narrative = self._render(event, scene)
        return PerceptionPacket(
            event=event,
            narrative=narrative,
            salience=salience,
            emotion_label=emotion,
            valence_delta=valence,
            arousal_delta=arousal,
            scene_text=scene.summary() if scene is not None else "",
            translator=self.name,
        )

    # ── 叙事模板 ─────────────────────────────────────────────────────────────

    def _render(self, event: GamePerceptionEvent, scene: PerceptionScene | None) -> str:
        d = event.detail
        where = self._where(event, scene)
        k = event.kind

        if k is GameEventKind.game_start:
            who = d.get("player_name", "一位旅者")
            return f"{who}踏入了这片沉睡的矿脉，新的旅程开始了。"
        if k is GameEventKind.game_clear:
            return "星门被推开了——旅者走完了这段路，星辉自高处倾落。"
        if k is GameEventKind.chapter_begin:
            title = str(d.get("title", "")).strip()
            return f"新的篇章开始了{('：' + title) if title else ''}，空气都变了味道。"
        if k is GameEventKind.room_enter:
            name = str(d.get("room_name", "")).strip() or "未知的角落"
            return f"旅者走进了「{name}」。"
        if k is GameEventKind.player_hurt:
            hp = int(d.get("hp", 0) or 0)
            hp_max = int(d.get("hp_max", 0) or 0)
            cause = str(d.get("cause", "")).strip()
            cause_part = f"，被{cause}所伤" if cause else ""
            hp_part = f"，生命只剩 {hp}/{hp_max}" if hp_max else ""
            return f"旅者受了伤{cause_part}{hp_part}。"
        if k is GameEventKind.player_heal:
            hp = int(d.get("hp", 0) or 0)
            hp_max = int(d.get("hp_max", 0) or 0)
            hp_part = f"，生命回到 {hp}/{hp_max}" if hp_max else ""
            return f"旅者的伤口正在愈合{hp_part}。"
        if k is GameEventKind.player_death:
            total = int(d.get("deaths", 0) or 0)
            times = f"（这已是第 {total} 次）" if total > 1 else ""
            return f"旅者倒下了{times}；灯台的火光会把人带回原处。"
        if k is GameEventKind.enemy_killed:
            name = str(d.get("enemy_name", "")).strip() or "敌影"
            return f"旅者的剑光落下，「{name}」散作了尘埃。"
        if k is GameEventKind.boss_fight_start:
            name = str(d.get("boss_name", "")).strip() or "庞然大物"
            return f"大地开始震动——「{name}」在{where}苏醒了，闸门轰然落下。"
        if k is GameEventKind.boss_defeated:
            name = str(d.get("boss_name", "")).strip() or "强敌"
            return f"「{name}」轰然倒地，封印开启，旅者的生命也被光补满。"
        if k is GameEventKind.ability_gain:
            ability = str(d.get("ability", "")).strip()
            name = _ABILITY_NAMES.get(ability, ability or "未知之物")
            return f"旅者获得了「{name}」，脚步或身法都和之前不一样了。"
        if k is GameEventKind.checkpoint_lit:
            room = str(d.get("room", "")).strip()
            room_part = f"（{room}）" if room else ""
            return f"一盏灯台被点亮了{room_part}，火光稳稳地立在那里。"
        if k is GameEventKind.npc_talk:
            npc = str(d.get("npc_name", "")).strip() or "有人"
            return f"旅者在{where}停下脚步，看向{npc}。"
        if k is GameEventKind.npc_line:
            npc = str(d.get("npc_name", "")).strip() or "守灯人"
            text = str(d.get("text", "")).strip()
            return f"{npc}说道：「{text}」" if text else f"{npc}开口说了些什么。"
        # custom / unknown
        text = str(d.get("text", "")).strip()
        if text:
            return text
        return f"世界里发生了一件事（{event.kind.value}）。"

    def _where(self, event: GamePerceptionEvent, scene: PerceptionScene | None) -> str:
        if scene is not None and scene.room_name:
            return f"「{scene.room_name}」"
        name = str(event.detail.get("room_name", "")).strip()
        return f"「{name}」" if name else "这片区域"
