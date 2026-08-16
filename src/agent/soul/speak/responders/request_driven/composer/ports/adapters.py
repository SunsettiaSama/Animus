from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .memory import MemoryHint, MemoryUnit
from .share_hint import ShareHintPort


class CallableMemorySearchPort:
    """把任意 search(session_id, query, limit, hint) 适配为 MemorySearchPort。"""

    def __init__(
        self,
        search_fn: Callable[[str, str, int, MemoryHint], list[MemoryUnit]] | None = None,
    ) -> None:
        self._search_fn = search_fn

    def bind(self, search_fn: Callable[[str, str, int, MemoryHint], list[MemoryUnit]]) -> None:
        self._search_fn = search_fn

    def search_related(
        self,
        session_id: str,
        query_text: str,
        *,
        limit: int,
        hint: MemoryHint = "related",
    ) -> list[MemoryUnit]:
        if self._search_fn is None:
            return []
        return list(self._search_fn(session_id, query_text, limit, hint))


class PresenceShareHintPort:
    def __init__(self, presence_reader: Callable[[str], str] | None = None) -> None:
        self._reader = presence_reader

    def bind(self, presence_reader: Callable[[str], str]) -> None:
        self._reader = presence_reader

    def share_query_text(self, session_id: str) -> str:
        if self._reader is None:
            return ""
        return str(self._reader(session_id) or "").strip()


def _text_from_search_hit(hit: dict[str, Any]) -> str:
    focus = str(hit.get("focus") or "").strip()
    body = ""
    for key in (
        "fact",
        "reconstructed_fact",
        "narrative",
        "content",
        "agent_relation",
        "trait_changelog",
    ):
        val = str(hit.get(key) or "").strip()
        if val:
            body = val
            break
    if focus and body:
        return f"{focus}：{body}"
    return body or focus


def units_from_search_hits(hits: list[Any], *, limit: int) -> list[MemoryUnit]:
    """Memory.api.search 返回的 scored dict → staging MemoryUnit。"""
    from ..domain.utterance import filter_utterance_units, is_noise_source

    out: list[MemoryUnit] = []
    for index, item in enumerate(hits):
        if len(out) >= limit:
            break
        if not isinstance(item, dict):
            continue
        kind = str(item.get("memory_type") or item.get("source") or "")
        if is_noise_source(kind):
            continue
        unit_id = str(item.get("id") or item.get("unit_id") or "").strip()
        text = _text_from_search_hit(item)
        if not unit_id or not text:
            continue
        source = str(item.get("source") or kind or "memory_search")
        if is_noise_source(source):
            continue
        score = float(item.get("final_score") or item.get("relevance") or 0.0)
        embedding_raw = item.get("embedding") or []
        embedding: tuple[float, ...] = ()
        if isinstance(embedding_raw, (list, tuple)) and embedding_raw:
            embedding = tuple(float(x) for x in embedding_raw)
        out.append(
            MemoryUnit(
                unit_id=unit_id,
                text=text,
                source=source,
                score=score,
                embedding=embedding,
            )
        )
    return filter_utterance_units(out)


def units_from_recall_candidates(candidates: list[Any], *, limit: int) -> list[MemoryUnit]:
    """只收具体记忆条目；画像/人格/system 类候选一律丢弃。"""
    from ..domain.utterance import filter_utterance_units, is_noise_source

    out: list[MemoryUnit] = []
    for index, item in enumerate(candidates):
        if len(out) >= limit:
            break
        if isinstance(item, dict):
            kind = str(
                item.get("kind")
                or item.get("type")
                or item.get("source")
                or item.get("channel")
                or ""
            )
            if is_noise_source(kind):
                continue
            text = str(
                item.get("text")
                or item.get("line")
                or item.get("content")
                or item.get("summary")
                or ""
            ).strip()
            unit_id = str(item.get("unit_id") or item.get("id") or f"cand-{index}")
            source = str(item.get("source") or "recall_candidate")
            if is_noise_source(source):
                continue
        elif hasattr(item, "unit_id") and (hasattr(item, "line") or hasattr(item, "text")):
            text = str(getattr(item, "line", "") or getattr(item, "text", "") or "").strip()
            unit_id = str(getattr(item, "unit_id", "") or f"cand-{index}").strip()
            source = str(getattr(item, "source", "") or "recall_candidate")
            if is_noise_source(source):
                continue
        else:
            text = str(item).strip()
            unit_id = f"cand-{index}"
            source = "recall_candidate"
        if not text:
            continue
        out.append(MemoryUnit(unit_id=unit_id, text=text, source=source))
    return filter_utterance_units(out)
