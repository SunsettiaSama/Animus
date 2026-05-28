from __future__ import annotations

import hashlib
import math

from agent.soul.memory.unit import MemoryUnit


def memory_unit_embed_text(unit: MemoryUnit) -> str:
    chunks = [
        unit.focus,
        getattr(unit, "fact", "") or "",
        getattr(unit, "perception", "") or "",
        getattr(unit, "reconstructed_fact", "") or "",
        getattr(unit, "narrative", "") or "",
    ]
    return " ".join(str(c) for c in chunks if c)


def focus_bucket(focus: str) -> str:
    text = focus.strip().lower()
    if not text:
        return "（未命名�?
    for sep in ("�?, ":", "�?, "-", "·", " "):
        if sep in text:
            text = text.split(sep, 1)[0].strip()
    return text[:16] or "（未命名�?


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def cluster_key(theme: str, unit_ids: list[str]) -> str:
    base = f"{focus_bucket(theme)}|{'|'.join(sorted(unit_ids))}"
    return hashlib.sha256(base.encode()).hexdigest()[:16]
