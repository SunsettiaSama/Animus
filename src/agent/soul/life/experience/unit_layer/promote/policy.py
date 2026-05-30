from __future__ import annotations

import re

from agent.soul.life.experience.domain.unit import ExperienceUnit

_PROMOTE_RES = re.compile(
    r"(深刻|重大|关键|难忘|强烈|很重要|印象深刻|值得记住|忘不掉|转折点|关键转折"
    r"|心绪难平|难以释怀|一直惦记着|久久不能平静|对我很重要|这轮很重要"
    r"|突然|意外|震惊|冲击|变故|出乎意料)",
)

_DEMOTE_RES = re.compile(
    r"(日常|寒暄|平淡|寻常|轻微|不太重要|随便聊聊|无足轻重|一带而过"
    r"|普通闲聊|没什么特别|不必记住|不重要|随口)",
)


def collect_self_narration(unit: ExperienceUnit) -> str:
    """汇总体验单元内可用于擢升判定的 agent 自叙与叙述文本。"""
    parts: list[str] = []
    note = unit.feeling.salience_note.strip()
    if note:
        parts.append(note)
    situation = unit.situation
    for field in ("narration", "prior_thought", "perception"):
        text = getattr(situation, field, "").strip()
        if text:
            parts.append(text)
    emotion = unit.feeling.emotion_label.strip()
    if emotion:
        parts.append(emotion)
    content = unit.action.content.strip()
    if content:
        parts.append(content)
    return "\n".join(parts)


def matches_promote_narration(text: str) -> bool:
    hay = text.strip()
    if not hay:
        return False
    return _PROMOTE_RES.search(hay) is not None


def matches_demote_narration(text: str) -> bool:
    hay = text.strip()
    if not hay:
        return False
    return _DEMOTE_RES.search(hay) is not None


def should_promote_to_memory(unit: ExperienceUnit) -> bool:
    """辅助信号：主路径已在 manage 入库时即时擢升。"""
    text = collect_self_narration(unit)
    if not text.strip():
        return False
    if matches_demote_narration(text):
        return False
    return matches_promote_narration(text)


def salience_score_from_narration(text: str) -> float:
    """将自叙文本投影为 life 层仍使用的显著性标量（供对话轮记账，非擢升门槛）。"""
    hay = text.strip()
    if not hay:
        return 0.3
    if matches_demote_narration(hay):
        return 0.2
    if matches_promote_narration(hay):
        return 0.7
    return 0.4
