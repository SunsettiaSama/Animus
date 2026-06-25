from __future__ import annotations

import random


class SurpriseLauncher:
    """意外事件累积概率触发器（storyview 顶层）。"""

    def __init__(
        self,
        initial_p: float = 0.02,
        growth_rate: float = 0.03,
    ) -> None:
        if not (0.0 < initial_p <= 1.0):
            raise ValueError(f"initial_p 必须在 (0, 1]，当前：{initial_p}")
        if not (0.0 < growth_rate <= 1.0):
            raise ValueError(f"growth_rate 必须在 (0, 1]，当前：{growth_rate}")
        self._initial_p = initial_p
        self._growth_rate = growth_rate
        self._p = initial_p

    @property
    def probability(self) -> float:
        return self._p

    def tick(self, elapsed_sec: float = 60.0) -> bool:
        steps = elapsed_sec / 60.0 if elapsed_sec > 0 else 1.0
        self._p = min(1.0, self._p + self._growth_rate * steps)
        if random.random() < self._p:
            self._p = self._initial_p
            return True
        return False

    def reset(self) -> None:
        self._p = self._initial_p
