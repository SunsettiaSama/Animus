from __future__ import annotations

import re
from typing import Iterable

# 策略与材料分离检查：动态材料层不允许出现指令性文本。
# 命中不阻断（材料仍照常注入），只在 notes 中告警，便于回归观察。
_POLICY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (label, re.compile(pattern))
    for label, pattern in (
        ("speak-tag", r"<\s*/?\s*speak\b"),
        ("compose-tag", r"\[\s*/?\s*(?:think|state|speak|action|recall)\b"),
        ("format-word", r"回复格式|输出格式|标签名按原样"),
        ("ban-word", r"请勿|不要把|禁止"),
        ("imperative-write", r"只写|必须写|不得写|用「你」给出"),
    )
)

_LINT_MAX_CHARS = 20_000


def lint_policy_text(text: str) -> list[str]:
    """返回命中的策略模式标签列表；无命中返回空表。"""
    body = text or ""
    if not body.strip():
        return []
    hits: set[str] = set()
    for label, pattern in _POLICY_PATTERNS:
        if pattern.search(body[:_LINT_MAX_CHARS]):
            hits.add(label)
    return sorted(hits)


def lint_policy_texts(texts: Iterable[str]) -> list[str]:
    merged = "\n".join(t for t in texts if t)
    return lint_policy_text(merged)
