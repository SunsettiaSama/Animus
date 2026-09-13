from __future__ import annotations

import re


_STOP = frozenset(
    "的 了 是 在 我 你 他 她 它 我们 你们 他们 这 那 有 和 与 或 就 也 还 要 会 能 可以".split()
)


def extract_keywords(text: str, *, max_tokens: int = 12) -> list[str]:
    raw = (text or "").strip().lower()
    if not raw:
        return []
    tokens: list[str] = []
    for part in re.split(r"[\s,，。！？!?;；、]+", raw):
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
