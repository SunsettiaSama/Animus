from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from .tokenizer import SimpleTokenizer, TokenizerPort


@dataclass
class Bm25Index:
    """纯 Python BM25（Okapi）。"""

    k1: float = 1.5
    b: float = 0.75
    tokenizer: TokenizerPort = field(default_factory=SimpleTokenizer)
    _doc_tokens: list[list[str]] = field(default_factory=list)
    _doc_ids: list[str] = field(default_factory=list)
    _df: Counter[str] = field(default_factory=Counter)
    _avgdl: float = 0.0

    def clear(self) -> None:
        self._doc_tokens.clear()
        self._doc_ids.clear()
        self._df.clear()
        self._avgdl = 0.0

    def build(self, documents: list[tuple[str, str]]) -> None:
        self.clear()
        lengths: list[int] = []
        for doc_id, text in documents:
            tokens = self.tokenizer.tokenize(text)
            self._doc_ids.append(doc_id)
            self._doc_tokens.append(tokens)
            lengths.append(len(tokens))
            for term in set(tokens):
                self._df[term] += 1
        self._avgdl = (sum(lengths) / len(lengths)) if lengths else 0.0

    def score(self, query: str, *, min_score: float = 0.0, top_k: int = 3) -> list[tuple[str, float]]:
        if not self._doc_ids:
            return []
        q_tokens = self.tokenizer.tokenize(query)
        if not q_tokens:
            return []
        n = len(self._doc_ids)
        scored: list[tuple[str, float]] = []
        for index, doc_id in enumerate(self._doc_ids):
            tokens = self._doc_tokens[index]
            if not tokens:
                continue
            tf = Counter(tokens)
            dl = len(tokens)
            total = 0.0
            for term in q_tokens:
                if term not in tf:
                    continue
                df = self._df.get(term, 0)
                idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
                freq = tf[term]
                denom = freq + self.k1 * (1.0 - self.b + self.b * dl / (self._avgdl or 1.0))
                total += idf * (freq * (self.k1 + 1.0) / denom)
            if total >= min_score:
                scored.append((doc_id, total))
        scored.sort(key=lambda item: item[1], reverse=True)
        if top_k < 1:
            return []
        return scored[:top_k]
