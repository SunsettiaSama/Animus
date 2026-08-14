from __future__ import annotations

import re

from ...contracts import FilledSegment, RhythmPlan


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[\u3002\uff01\uff1f!?\uff1b;\n])\s*")


def split_into_parts(text: str, count: int) -> list[str]:
    cleaned = text.strip()
    if count <= 1 or not cleaned:
        return [cleaned] if cleaned else [""]
    chunks = _SENTENCE_SPLIT_RE.split(cleaned)
    chunks = [c.strip() for c in chunks if c.strip()]
    if len(chunks) <= 1:
        mid = max(1, len(cleaned) // count)
        parts: list[str] = []
        cursor = 0
        for idx in range(count):
            if idx == count - 1:
                parts.append(cleaned[cursor:].strip())
                break
            parts.append(cleaned[cursor : cursor + mid].strip())
            cursor += mid
        return [p for p in parts if p] or [cleaned]
    if len(chunks) == count:
        return chunks
    if len(chunks) > count:
        head = chunks[: count - 1]
        tail = "".join(chunks[count - 1 :])
        return head + [tail]
    while len(chunks) < count:
        chunks.append("")
    return chunks[:count]


def fill_segments(body: str, rhythm: RhythmPlan) -> tuple[FilledSegment, ...]:
    if not rhythm.segments:
        return ()
    parts = split_into_parts(body, len(rhythm.segments))
    filled: list[FilledSegment] = []
    for idx, seg in enumerate(rhythm.segments):
        text = parts[idx] if idx < len(parts) else ""
        if not text and idx == 0:
            text = body
        if not text:
            continue
        filled.append(
            FilledSegment(
                text=text,
                wait_reason=seg.wait_reason,
                continuity=seg.continuity,
            )
        )
    if not filled:
        first = rhythm.segments[0]
        filled.append(
            FilledSegment(
                text=body,
                wait_reason=first.wait_reason,
                continuity=first.continuity,
            )
        )
    return tuple(filled)
