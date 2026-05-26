from __future__ import annotations

import re

_SENTENCE_BREAK = re.compile(r"(?<=[。！？；\n])|(?<=[.!?;]\s)")


def split_sentences(text: str, *, min_chars: int = 8) -> list[str]:
    """按句读符切分文本，并合并过短碎片。"""
    normalized = text.strip()
    if not normalized:
        return []

    parts = [piece.strip() for piece in _SENTENCE_BREAK.split(normalized) if piece.strip()]
    if not parts:
        return [normalized]

    merged: list[str] = []
    buffer = ""
    for part in parts:
        if not buffer:
            buffer = part
            continue
        if len(buffer) < min_chars:
            buffer = f"{buffer}{part}"
        else:
            merged.append(buffer)
            buffer = part
    if buffer:
        if merged and len(buffer) < min_chars:
            merged[-1] = f"{merged[-1]}{buffer}"
        else:
            merged.append(buffer)
    return merged
