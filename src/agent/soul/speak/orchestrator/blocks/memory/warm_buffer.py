from __future__ import annotations

import re

from agent.soul.memory.graph.keywords import extract_keywords
from agent.soul.speak.orchestrator.queue.memory import (
    MemoryBufferItem,
    MemoryComposePullResult,
    ComposeMemoryBuffer,
)


def _match_terms(user_text: str) -> list[str]:
    raw = (user_text or "").strip().lower()
    terms = list(extract_keywords(raw))
    seen = set(terms)
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", raw):
        max_width = min(8, len(run))
        for width in range(max_width, 1, -1):
            for start in range(len(run) - width + 1):
                chunk = run[start : start + width]
                if chunk in seen:
                    continue
                seen.add(chunk)
                terms.append(chunk)
                if len(terms) >= 32:
                    return terms
    return terms


def regex_similarity_score(user_text: str, line: str) -> float:
    terms = _match_terms(user_text)
    if not terms:
        return 0.0
    hay = line.lower()
    hits = sum(1 for term in terms if term in hay)
    if hits <= 0:
        return 0.0
    return float(hits) / float(len(terms))


class MemoryWarmBuffer(ComposeMemoryBuffer):
    """Orchestrator 记忆预热 buffer：social / warm_spread / 轮次队列 + 每轮正则优先注入。"""

    def pull_for_compose(
        self,
        session_id: str,
        current_turn_index: int,
        *,
        keyword_wait_ms: int = 200,
        budget: int = 5,
        merge_ratio: float | None = None,
        user_text: str = "",
    ) -> MemoryComposePullResult:
        pulled = super().pull_for_compose(
            session_id,
            current_turn_index,
            keyword_wait_ms=keyword_wait_ms,
            budget=budget,
            merge_ratio=merge_ratio,
        )
        query = user_text.strip()
        if not query:
            return pulled

        priority_line, priority_id = self._pick_regex_priority(
            session_id,
            query,
            pulled,
        )
        if not priority_line or not priority_id:
            return pulled

        if priority_id in pulled.inject_unit_ids:
            return pulled

        inject_lines = [priority_line] + [
            line
            for line, uid in zip(pulled.inject_lines, pulled.inject_unit_ids)
            if uid != priority_id
        ]
        inject_ids = [priority_id] + [
            uid for uid in pulled.inject_unit_ids if uid != priority_id
        ]
        budget = max(1, budget)
        pulled.inject_lines = inject_lines[:budget]
        pulled.inject_unit_ids = inject_ids[:budget]
        if "regex_priority" not in pulled.sources:
            pulled.sources = ["regex_priority", *list(pulled.sources)]
        return pulled

    def _pick_regex_priority(
        self,
        session_id: str,
        user_text: str,
        pulled: MemoryComposePullResult,
    ) -> tuple[str, str]:
        best_score = 0.0
        best_line = ""
        best_id = ""
        for line, uid in self._iter_candidates(session_id, pulled):
            if self._is_consumed(session_id, uid):
                continue
            score = regex_similarity_score(user_text, line)
            if score <= best_score:
                continue
            best_score = score
            best_line = line
            best_id = uid
        if best_score <= 0.0 or not best_id:
            return "", ""
        self.record_recall_pick(session_id, best_id)
        return best_line, best_id

    def _iter_candidates(
        self,
        session_id: str,
        pulled: MemoryComposePullResult,
    ):
        seen: set[str] = set()

        def _yield_pairs(lines: list[str], unit_ids: list[str]):
            for line, uid in zip(lines, unit_ids):
                key = uid.strip()
                if not key or key in seen:
                    continue
                seen.add(key)
                yield line, key

        social = self._social_prefetch.get(session_id)
        if social is not None:
            yield from _yield_pairs(list(social.lines), list(social.unit_ids))
        for line, uid in _yield_pairs(
            list(pulled.warm_spread_lines),
            list(pulled.warm_spread_unit_ids),
        ):
            yield line, uid
        for line, uid in _yield_pairs(list(pulled.inject_lines), list(pulled.inject_unit_ids)):
            yield line, uid

        queue = self._turn_queues.get(session_id)
        if not queue:
            return
        for item in queue:
            if item.source not in ("keyword", "emergence"):
                continue
            yield from _yield_pairs(list(item.lines), list(item.unit_ids))
