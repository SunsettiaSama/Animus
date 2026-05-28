from __future__ import annotations

import re

from agent.soul.memory.emotion_intensity import node_emotion_intensity

_UNFINISHED_PATTERNS = re.compile(
    r"(还没|尚未|未完成|未解决|没结果|悬而未决|不了了之|待续|进行中|"
    r"怎么办|为什么|会不会|能否|能不能|？|\?|"
    r"todo|pending|unfinished|open loop)",
    re.IGNORECASE,
)


def emotion_intensity_of(node) -> float:
    stored = float(getattr(node, "emotion_intensity", 0.0) or 0.0)
    inferred = node_emotion_intensity(node)
    return max(stored, inferred)


def unfinished_score_of(node) -> float:
    meta = getattr(node, "meta", None) or {}
    if meta.get("unfinished") or meta.get("open_loop"):
        return 1.0

    chunks: list[str] = []
    for attr in ("focus", "fact", "perception", "reconstructed_fact", "content", "narrative"):
        val = getattr(node, attr, "")
        if val:
            chunks.append(str(val))
    text = " ".join(chunks)
    if not text.strip():
        return 0.0

    score = 0.0
    if _UNFINISHED_PATTERNS.search(text):
        score = max(score, 0.72)
    if text.rstrip().endswith(("？", "?")):
        score = max(score, 0.55)
    if getattr(node, "narrative_ref_count", 0) == 0 and getattr(node, "rehearsal_count", 0) >= 1:
        score = max(score, 0.48)
    return score


def is_high_emotion(
    node,
    *,
    threshold: float,
) -> tuple[bool, float]:
    if node.MEMORY_TYPE not in ("factual", "reconstructive"):
        return False, 0.0
    emotion = emotion_intensity_of(node)
    return emotion >= threshold, emotion


def is_ruminatable(
    node,
    *,
    emotion_threshold: float,
    unfinished_threshold: float,
) -> tuple[bool, float, float]:
    if node.MEMORY_TYPE not in ("factual", "reconstructive"):
        return False, 0.0, 0.0
    emotion = emotion_intensity_of(node)
    unfinished = unfinished_score_of(node)
    ok = emotion >= emotion_threshold and unfinished >= unfinished_threshold
    return ok, emotion, unfinished


def entry_weight(emotion: float, unfinished: float) -> float:
    return emotion * unfinished
