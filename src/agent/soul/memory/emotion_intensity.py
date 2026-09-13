from __future__ import annotations

import re

_HIGH = (
    "崩溃", "绝望", "痛不欲生", "狂喜", "欣喜若狂", "暴怒", "怒火中烧",
    "恐惧至极", "吓坏了", "极度", "强烈", "无比", "彻底", "撕心裂肺",
    "痛哭", "狂躁", "万念俱灰", "怒不可遏",
)
_MID = (
    "难过", "伤心", "沮丧", "抑郁", "焦虑", "不安", "愤怒", "生气",
    "害怕", "恐惧", "紧张", "兴奋", "激动", "开心", "高兴", "快乐",
    "欣慰", "感动", "委屈", "失落", "孤独", "寂寞", "烦躁", "厌恶",
    "反感", "羞愧", "尴尬", "担忧", "惆怅", "心酸", "振奋", "惊喜",
)
_LOW = (
    "有点", "略微", "稍微", "稍稍", "一点", "些许", "平静", "淡然",
    "淡定", "还好", "一般", "普通", "安静", "从容", "冷静",
)

_SUBJECTIVE_ATTRS = (
    "perception",
    "content",
    "narrative",
    "reconstructed_fact",
    "fact",
    "focus",
)


def infer_emotion_intensity(emotion: str = "", *texts: str) -> float:
    """从情绪标签 + 主观/叙事文本中的关键词映射情绪烈度（0~1）。"""
    parts = [str(t).strip() for t in texts if t and str(t).strip()]
    em = (emotion or "").strip()
    if em:
        parts.append(em)
    combined = " ".join(parts).lower()
    if not combined:
        return 0.0

    score = 0.0
    for kw in _HIGH:
        if kw in combined:
            score = max(score, 0.82)
    for kw in _MID:
        if kw in combined:
            score = max(score, 0.52)
    for kw in _LOW:
        if kw in combined:
            score = max(score, 0.22)

    if re.search(r"[!！]{2,}", combined):
        score = min(1.0, score + 0.12)
    elif "!" in combined or "！" in combined:
        score = min(1.0, score + 0.05)

    return min(1.0, score)


def node_emotion_intensity(node) -> float:
    texts = [getattr(node, attr, "") for attr in _SUBJECTIVE_ATTRS]
    return infer_emotion_intensity(getattr(node, "emotion", ""), *texts)
