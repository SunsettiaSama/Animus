from __future__ import annotations

import re


_STOP = frozenset(
    "çš?äº?æ˜?åœ?æˆ?ä½?ä»?å¥?å®?æˆ‘ä»¬ ä½ ä»¬ ä»–ä»¬ è¿?é‚?æœ?å’?ä¸?æˆ?å°?ä¹?è¿?è¦?ä¼?èƒ?å¯ä»¥".split()
)


def extract_keywords(text: str, *, max_tokens: int = 12) -> list[str]:
    raw = (text or "").strip().lower()
    if not raw:
        return []
    tokens: list[str] = []
    for part in re.split(r"[\s,ï¼Œã€‚ï¼ï¼??;ï¼›ã€]+", raw):
        part = part.strip()
        if len(part) < 2 or part in _STOP:
            continue
        tokens.append(part)
    seen: set[str] = set()
    out: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= max_tokens:
            break
    return out
