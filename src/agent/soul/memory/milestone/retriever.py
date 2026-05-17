from __future__ import annotations

import re
from typing import Callable

from ...memory.milestone.entry import MilestoneEntry

# ── 分词后端 ─────────────────────────────────────────────────────────────────
# 优先使用 jieba；未安装时自动降级为字符 bigram + 精确子串策略
try:
    import jieba  # type: ignore
    jieba.initialize()  # pre-build prefix dict at import time, not on first cut()

    def _tokenize(text: str) -> set[str]:
        return {w.strip() for w in jieba.cut(text) if w.strip()}

    _USING_JIEBA = True
except ModuleNotFoundError:
    _USING_JIEBA = False

    def _bigrams(text: str) -> set[str]:
        t = re.sub(r"\s+", "", text)
        return {t[i : i + 2] for i in range(len(t) - 1)} if len(t) >= 2 else set()

    def _tokenize(text: str) -> set[str]:  # type: ignore[misc]
        ascii_words = set(re.findall(r"[a-zA-Z0-9]+", text.lower()))
        return ascii_words | _bigrams(text)


def _keyword_score(entry: MilestoneEntry, query: str) -> float:
    """Return a match score for *entry* against *query*.

    Two signals are combined:
    1. Exact substring hit  — keyword (as a whole string) appears inside the query.
       This is the primary signal for LLM-extracted Chinese word phrases.
    2. Tokenised overlap    — using whatever backend is available (jieba / bigram).

    The exact-substring signal is weighted higher so that a single precise
    keyword match beats many unrelated bigram coincidences.
    """
    query_lower = query.lower()

    # --- signal 1: exact substring (keyword phrase ⊆ query) ---
    exact_hits = sum(
        1 for kw in entry.keywords if kw and kw.lower() in query_lower
    )
    # also check summary keywords as a bonus
    if entry.summary.lower() and any(
        kw.lower() in query_lower for kw in entry.summary.split() if len(kw) >= 2
    ):
        exact_hits += 0.5

    if exact_hits == 0 and not _USING_JIEBA:
        # --- signal 2: bigram overlap (fallback only) ---
        query_tokens = _tokenize(query_lower)
        cand_tokens = _tokenize(
            " ".join(entry.keywords) + " " + entry.summary
        )
        overlap = len(query_tokens & cand_tokens)
        return overlap * 0.3
    elif exact_hits == 0 and _USING_JIEBA:
        # --- signal 2: jieba token overlap ---
        query_tokens = _tokenize(query)
        cand_tokens = _tokenize(" ".join(entry.keywords) + " " + entry.summary)
        overlap = len(query_tokens & cand_tokens)
        return overlap * 0.5

    return float(exact_hits) * 2.0


class MilestoneRetriever:
    """Retriever for milestone entries.

    Matching strategy (no FAISS needed):
    - Primary: exact keyword-phrase substring check against the query.
    - Secondary: tokenised overlap (jieba if available, else character bigrams).
    """

    def retrieve(
        self,
        entries: list[MilestoneEntry],
        query: str,
        top_k: int = 2,
    ) -> list[MilestoneEntry]:
        if not entries or not query.strip():
            return []

        scored: list[tuple[float, MilestoneEntry]] = []
        for entry in entries:
            s = _keyword_score(entry, query)
            if s > 0:
                scored.append((s, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]
