from __future__ import annotations

import re

IDENTITY_PROMPT_TARGET_CHARS = 150
IDENTITY_HARD_MAX_CHARS = 200
STABLE_HARD_MAX_CHARS = IDENTITY_HARD_MAX_CHARS
NARRATIVE_HARD_MAX_CHARS = IDENTITY_HARD_MAX_CHARS

NARRATIVE_MAX_CHARS = NARRATIVE_HARD_MAX_CHARS
IDENTITY_MAX_CHARS = IDENTITY_HARD_MAX_CHARS

_SENTENCE_END = re.compile(r"[。！？；\n]")


def clamp_identity_text(
    text: str,
    *,
    hard_max: int = IDENTITY_HARD_MAX_CHARS,
) -> str:
    normalized = " ".join(text.strip().split())
    if hard_max <= 0 or len(normalized) <= hard_max:
        return normalized
    cut = normalized[:hard_max]
    last = -1
    for match in _SENTENCE_END.finditer(cut):
        last = match.end()
    if last >= max(40, hard_max // 3):
        return cut[:last].rstrip()
    return cut.rstrip()
