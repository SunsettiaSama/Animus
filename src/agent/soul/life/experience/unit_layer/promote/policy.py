from __future__ import annotations

from agent.soul.life.experience.domain.unit import ExperienceUnit


def collect_self_narration(unit: ExperienceUnit) -> str:
    """汇总体验单元内可用于展示的 agent 自叙与叙述文本。"""
    parts: list[str] = []
    why = unit.feeling.impression_why.strip()
    if why:
        parts.append(why)
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


def should_promote_to_memory(unit: ExperienceUnit) -> bool:
    """仅当 agent 显式标注 promote_to_memory 时擢升（无数值/正则硬门槛）。"""
    feeling = unit.feeling
    if not feeling.annotation_decided:
        return False
    return bool(feeling.promote_to_memory)


def salience_score_from_narration(text: str) -> float:
    """将自叙文本投影为 life 层仍使用的显著性标量（供对话轮记账，非擢升门槛）。"""
    hay = text.strip()
    if not hay:
        return 0.3
    if any(token in hay for token in ("日常", "寒暄", "平淡", "不太重要", "无足轻重")):
        return 0.2
    if any(token in hay for token in ("深刻", "重要", "难忘", "强烈", "转折")):
        return 0.7
    return 0.4
