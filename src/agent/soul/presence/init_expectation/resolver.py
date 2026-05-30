from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from agent.soul.memory.embed_text import cosine_similarity

from .anchors import TIER_ANCHORS, TierAnchor
from .persona_text import persona_text_from_snapshot
from .tier import ExpectationTier, parse_expectation_tier


class EmbedderPort(Protocol):
    def embed(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class TierResolveResult:
    tier: ExpectationTier
    keyword_scores: dict[str, float]
    embedding_scores: dict[str, float]
    combined_scores: dict[str, float]
    notes: list[str]


def _keyword_score(text: str, anchor: TierAnchor) -> float:
    lowered = text.lower()
    hits = 0
    for word in anchor.keywords:
        token = word.lower()
        if token in lowered:
            hits += 1
    if hits == 0:
        return 0.0
    return min(1.0, hits / max(3.0, len(anchor.keywords) * 0.15))


def _normalize_scores(raw: dict[ExpectationTier, float]) -> dict[ExpectationTier, float]:
    peak = max(raw.values()) if raw else 0.0
    if peak <= 0.0:
        return {tier: 0.0 for tier in raw}
    return {tier: value / peak for tier, value in raw.items()}


def resolve_expectation_tier(
    persona_snapshot: dict[str, Any],
    *,
    embedder: EmbedderPort | None = None,
    override: str | ExpectationTier | None = None,
    keyword_weight: float = 0.42,
) -> TierResolveResult:
    forced = parse_expectation_tier(override)
    if forced is not None:
        return TierResolveResult(
            tier=forced,
            keyword_scores={},
            embedding_scores={},
            combined_scores={forced.value: 1.0},
            notes=[f"tier override → {forced.value}"],
        )

    text = persona_text_from_snapshot(persona_snapshot)
    if not text.strip():
        return TierResolveResult(
            tier=ExpectationTier.medium,
            keyword_scores={},
            embedding_scores={},
            combined_scores={ExpectationTier.medium.value: 1.0},
            notes=["empty persona text → default 中"],
        )

    keyword_raw = {anchor.tier: _keyword_score(text, anchor) for anchor in TIER_ANCHORS}
    keyword_scores = {
        tier.value: score for tier, score in _normalize_scores(keyword_raw).items()
    }

    embedding_scores: dict[str, float] = {}
    combined_raw: dict[ExpectationTier, float] = dict(keyword_raw)
    notes: list[str] = []

    if embedder is not None:
        persona_vec = embedder.embed(text[:2000])
        embed_raw: dict[ExpectationTier, float] = {}
        for anchor in TIER_ANCHORS:
            anchor_vec = embedder.embed(anchor.embedding_summary)
            embed_raw[anchor.tier] = cosine_similarity(persona_vec, anchor_vec)
        embedding_norm = _normalize_scores(embed_raw)
        embedding_scores = {tier.value: score for tier, score in embedding_norm.items()}
        embed_w = 1.0 - keyword_weight
        for tier in ExpectationTier:
            combined_raw[tier] = (
                keyword_raw.get(tier, 0.0) * keyword_weight
                + embedding_norm.get(tier, 0.0) * embed_w
            )
        notes.append("keyword + embedding fusion")
    else:
        notes.append("keyword only (no embedder)")

    combined_norm = _normalize_scores(combined_raw)
    combined_scores = {tier.value: score for tier, score in combined_norm.items()}
    best = max(combined_raw.items(), key=lambda item: item[1])[0]
    if combined_raw[best] <= 0.0:
        best = ExpectationTier.medium
        notes.append("no signal → default 中")

    return TierResolveResult(
        tier=best,
        keyword_scores=keyword_scores,
        embedding_scores=embedding_scores,
        combined_scores=combined_scores,
        notes=notes,
    )
