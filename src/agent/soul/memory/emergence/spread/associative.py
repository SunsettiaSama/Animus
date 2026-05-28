from __future__ import annotations

import random

from agent.soul.memory.graph.scored import ScoredUnit


def sample_associative_intensity() -> float:
    return min(1.0, abs(random.gauss(0.0, 1.0)))


def perturb_vector(vector: list[float], intensity: float, *, sigma: float) -> list[float]:
    if not vector or intensity <= 0.0:
        return list(vector)
    scale = intensity * sigma
    return [v + random.gauss(0.0, scale) for v in vector]


def merge_hybrid_results(
    precise: list[ScoredUnit],
    associative: list[ScoredUnit],
) -> tuple[list[ScoredUnit], list[ScoredUnit]]:
    precise_ids = {s.unit.id for s in precise}
    associative_only: list[ScoredUnit] = []
    for s in associative:
        if s.unit.id in precise_ids:
            continue
        associative_only.append(s)
    return precise, associative_only
