from __future__ import annotations

import re

_FORBIDDEN_MARKERS = (
    "情感：",
    "身体：",
    "认知：",
    "感知：",
    "【当下态·状态】",
    "emotion_label",
    "mood_span",
)


def extract_plain_text(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```\s*$", "", text, flags=re.DOTALL)
    return text.strip().strip('"').strip("'").strip()


def validate_agent_prose(text: str) -> str:
    body = extract_plain_text(text)
    if not body:
        raise ValueError("PresenceUnitDistillWriter: 蒸馏正文为空")
    for marker in _FORBIDDEN_MARKERS:
        if marker in body:
            raise ValueError(
                f"PresenceUnitDistillWriter: 正文含工程标记 {marker!r}",
            )
    if body.lstrip().startswith(("{", "[")):
        raise ValueError("PresenceUnitDistillWriter: 正文不得为 JSON")
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if len(lines) > 4:
        raise ValueError("PresenceUnitDistillWriter: 正文须为连贯段落，勿多行列表")
    return body


def clamp_chars(text: str, max_chars: int) -> str:
    text = text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()
