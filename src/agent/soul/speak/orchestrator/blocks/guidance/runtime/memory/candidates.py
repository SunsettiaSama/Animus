from __future__ import annotations

import random

from ..control.candidate_types import RecallPlannerCandidate
from .pick_weights import PICK_WEIGHT_DEFAULT, RecallPickWeightPort

MAX_RECALL_PLANNER_CANDIDATES = 3
MAX_SOCIAL_RECALL_CANDIDATES = 1
MAX_EVENT_WANDER_CANDIDATES = 1

__all__ = [
    "MAX_EVENT_WANDER_CANDIDATES",
    "MAX_RECALL_PLANNER_CANDIDATES",
    "MAX_SOCIAL_RECALL_CANDIDATES",
    "RecallPlannerCandidate",
    "build_recall_candidates_from_pull",
    "format_recall_candidates",
]


def _aligned_pairs(lines: list[str], unit_ids: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for line, uid in zip(lines, unit_ids):
        text = line.strip()
        memory_id = uid.strip()
        if text and memory_id:
            pairs.append((text, memory_id))
    return pairs


def _dedupe_pairs(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    from agent.soul.memory.emergence.line_dedup import dedupe_memory_line_pairs

    if not pairs:
        return []
    lines, unit_ids = zip(*pairs)
    merged_lines, merged_ids = dedupe_memory_line_pairs(list(lines), list(unit_ids))
    return list(zip(merged_lines, merged_ids))


def _social_recency_weights(count: int) -> list[float]:
    if count < 1:
        return []
    if count == 1:
        return [1.0]
    return [0.55 + 0.45 * ((index + 1) / count) for index in range(count)]


def _unit_weight(
    session_id: str,
    unit_id: str,
    base: float,
    pick_weights: RecallPickWeightPort | None,
) -> float:
    if pick_weights is None or not session_id.strip():
        return base
    penalty = pick_weights.recall_pick_weight(session_id, unit_id)
    return base * penalty


def _weighted_pick(
    pairs: list[tuple[str, str]],
    weights: list[float],
) -> tuple[str, str] | None:
    if not pairs:
        return None
    if len(pairs) == 1:
        return pairs[0]
    total = sum(weights)
    if total <= 0:
        return random.choice(pairs)
    threshold = random.uniform(0, total)
    acc = 0.0
    for pair, weight in zip(pairs, weights):
        acc += weight
        if threshold <= acc:
            return pair
    return pairs[-1]


def _pick_social_pair(
    pulled,
    *,
    session_id: str,
    pick_weights: RecallPickWeightPort | None,
) -> tuple[str, str] | None:
    pairs = _dedupe_pairs(_aligned_pairs(
        list(pulled.social_prefetch_lines),
        list(pulled.social_prefetch_unit_ids),
    ))
    if not pairs:
        return None
    recency = _social_recency_weights(len(pairs))
    weights = [
        _unit_weight(session_id, uid, base, pick_weights)
        for (_, uid), base in zip(pairs, recency)
    ]
    return _weighted_pick(pairs, weights)


def _pick_event_pair(
    pulled,
    *,
    session_id: str,
    pick_weights: RecallPickWeightPort | None,
) -> tuple[str, str, str] | None:
    wander_pairs = _dedupe_pairs(_aligned_pairs(
        list(pulled.warm_spread_lines),
        list(pulled.warm_spread_unit_ids),
    ))
    if wander_pairs:
        weights = [
            _unit_weight(session_id, uid, PICK_WEIGHT_DEFAULT, pick_weights)
            for _, uid in wander_pairs
        ]
        line, uid = _weighted_pick(wander_pairs, weights)
        if line is not None:
            return ("event·漫游", line, uid)

    event_pairs = _dedupe_pairs(_aligned_pairs(
        list(pulled.inject.lines),
        list(pulled.inject.unit_ids),
    ))
    if not event_pairs:
        return None
    weights = [
        _unit_weight(session_id, uid, PICK_WEIGHT_DEFAULT, pick_weights)
        for _, uid in event_pairs
    ]
    line, uid = _weighted_pick(event_pairs, weights)
    if line is None:
        return None
    return ("event·涌现", line, uid)


def _record_picks(
    session_id: str,
    unit_ids: list[str],
    pick_weights: RecallPickWeightPort | None,
) -> None:
    if pick_weights is None or not session_id.strip():
        return
    seen: set[str] = set()
    for unit_id in unit_ids:
        uid = unit_id.strip()
        if not uid or uid in seen:
            continue
        seen.add(uid)
        pick_weights.record_recall_pick(session_id, uid)


def build_recall_candidates_from_pull(
    pulled,
    *,
    session_id: str = "",
    pick_weights: RecallPickWeightPort | None = None,
    max_items: int = MAX_RECALL_PLANNER_CANDIDATES,
) -> tuple[RecallPlannerCandidate, ...]:
    """social / event 均在池内加权随机；上轮入选 unit 下轮降权（不置零）。"""
    slots: list[tuple[str, str, str]] = []

    social = _pick_social_pair(
        pulled,
        session_id=session_id,
        pick_weights=pick_weights,
    )
    if social is not None:
        slots.append(("social·最新", social[0], social[1]))

    event = _pick_event_pair(
        pulled,
        session_id=session_id,
        pick_weights=pick_weights,
    )
    if event is not None:
        slots.append(event)

    cap = max(1, max_items)
    slots = slots[:cap]

    candidates = tuple(
        RecallPlannerCandidate(
            planner_index=index,
            unit_id=uid,
            line=f"（{tag}）{line}",
        )
        for index, (tag, line, uid) in enumerate(slots)
    )
    _record_picks(
        session_id,
        [item.unit_id for item in candidates],
        pick_weights,
    )
    return candidates


def format_recall_candidates(candidates: tuple[RecallPlannerCandidate, ...]) -> str:
    if not candidates:
        return ""
    lines = [
        "回忆候选（social 偏新检索 + event 漫游/涌现池；上轮入选的 unit 下轮降权后加权抽样；"
        "有候选≠必须叙述，仅下列下标可 emit_recall_index）：",
    ]
    for item in candidates:
        lines.append(f"- [{item.planner_index}] {item.line}")
    return "\n".join(lines)
