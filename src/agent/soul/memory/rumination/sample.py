from __future__ import annotations

import random

from agent.soul.memory.rumination.types import RuminationBufferEntry


def gaussian_pick(
    entries: list[RuminationBufferEntry],
    *,
    sigma: float = 0.25,
) -> RuminationBufferEntry | None:
    """对 buffer 权重施加高斯扰动后抽样一个 node。"""
    if not entries:
        return None
    if len(entries) == 1:
        return entries[0]

    perturbed: list[tuple[RuminationBufferEntry, float]] = []
    for entry in entries:
        base = max(entry.weight, 1e-6)
        noise = random.gauss(0.0, sigma)
        perturbed.append((entry, max(0.0, base * (1.0 + noise))))

    total = sum(w for _, w in perturbed)
    if total <= 0.0:
        return random.choice(entries)

    threshold = random.random() * total
    acc = 0.0
    for entry, weight in perturbed:
        acc += weight
        if acc >= threshold:
            return entry
    return perturbed[-1][0]
