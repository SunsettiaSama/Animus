from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SpeakSubjectiveChunk:
    """可选的轮级主观草稿（speak 层持有，不硬写 presence FSM）。

    连续体验由 presence 的 ``DialogueSessionTransition`` 维护；
    会话闭合时经 ``finalize_dialogue_experience`` 注入 memory。
    """

    perception: str = ""
    narration: str = ""
    prior_thought: str = ""


@dataclass
class SpeakFeelingChunk:
    """体验感受的第一人称自叙（speak 层不做量化）。"""

    emotion: str = ""   # 命名情绪，如「专注」「有些不安」
    salience: str = ""  # 显著性自叙，如「这只是日常寒暄」「这轮对我很重要」
    valence: str = ""   # 情感走向自叙，如「心里渐渐安心」「略感压迫」
    arousal: str = ""   # 唤醒/能量自叙，如「精神集中」「有些疲惫」


@dataclass(frozen=True)
class ResolvedFeeling:
    """bridge 边界：将自叙感受投影为 life 层仍使用的数值（仅内部转换）。"""

    salience: float
    valence_delta: float
    arousal_delta: float
    emotion_label: str


@dataclass
class SpeakTurnChunk:
    """一轮完整对话：原始话语 + 主观描述 + 感受自叙。"""

    session_id: str
    user_text: str
    agent_text: str
    subjective: SpeakSubjectiveChunk = field(default_factory=SpeakSubjectiveChunk)
    feeling: SpeakFeelingChunk = field(default_factory=SpeakFeelingChunk)
    activated_memory_ids: list[str] = field(default_factory=list)
    proactive_intent_id: str = ""


def resolve_subjective(chunk: SpeakTurnChunk) -> SpeakSubjectiveChunk:
    """主观字段为空时，用原始话语填充（与旧 recorder 默认一致）。"""
    subj = chunk.subjective
    if subj.perception.strip() or subj.narration.strip() or subj.prior_thought.strip():
        return subj
    return SpeakSubjectiveChunk(
        perception=chunk.user_text.strip(),
        narration=chunk.agent_text.strip(),
    )


def feeling_self_narration(feeling: SpeakFeelingChunk) -> str:
    """合并轮级感受自叙，供 life 层 salience_note 与正则擢升判定。"""
    parts: list[str] = []
    for text in (feeling.salience, feeling.emotion, feeling.valence, feeling.arousal):
        line = text.strip()
        if line:
            parts.append(line)
    return "；".join(parts)


def _estimate_salience(text: str) -> float:
    from agent.soul.life.experience.memory_promotion import salience_score_from_narration

    return salience_score_from_narration(text)


def _estimate_valence(text: str) -> float:
    t = text.strip()
    if not t:
        return 0.0
    if any(k in t for k in ("安心", "愉快", "满足", "轻松", "向上", "positive")):
        return 0.2
    if any(k in t for k in ("不安", "沮丧", "向下", "negative", "焦虑", "压迫", "失落")):
        return -0.2
    return 0.0


def _estimate_arousal(text: str) -> float:
    t = text.strip()
    if not t:
        return 0.0
    if any(k in t for k in ("紧绷", "兴奋", "活跃", "唤醒", "急促", "集中")):
        return 0.2
    if any(k in t for k in ("平静", "放松", "疲惫", "沉", "倦")):
        return -0.1
    return 0.0


def resolve_feeling(chunk: SpeakTurnChunk) -> ResolvedFeeling:
    """将感受自叙投影为 life/memory 入口所需的数值（仅在 bridge 边界转换）。"""
    feeling = chunk.feeling
    return ResolvedFeeling(
        salience=_estimate_salience(feeling.salience),
        valence_delta=_estimate_valence(feeling.valence),
        arousal_delta=_estimate_arousal(feeling.arousal),
        emotion_label=feeling.emotion.strip(),
    )
