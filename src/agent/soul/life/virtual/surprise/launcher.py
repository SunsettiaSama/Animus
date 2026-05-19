from __future__ import annotations

import random


class SurpriseLauncher:
    """意外事件累积概率触发器。

    每次 ``tick()`` 被调用时，内部概率按 ``growth_rate`` 增长，
    直至达到 1.0（此时下次 tick 必然触发）。触发后概率重置为 ``initial_p``，
    重新开始下一轮累积。

    数学模型
    --------
    p(n) = min(1.0,  initial_p + growth_rate × n)

    期望触发间隔约为 ``1 / (2 × growth_rate)`` 次 tick。
    以 60 秒 tick 计：
    - ``growth_rate=0.03`` → 期望约 17 次 tick（约 17 分钟）触发一次
    - ``growth_rate=0.015`` → 期望约 33 次 tick（约 33 分钟）触发一次
    """

    def __init__(
        self,
        initial_p: float = 0.02,
        growth_rate: float = 0.03,
    ) -> None:
        if not (0.0 < initial_p <= 1.0):
            raise ValueError(f"initial_p 必须在 (0, 1]，当前：{initial_p}")
        if not (0.0 < growth_rate <= 1.0):
            raise ValueError(f"growth_rate 必须在 (0, 1]，当前：{growth_rate}")
        self._initial_p   = initial_p
        self._growth_rate = growth_rate
        self._p           = initial_p

    @property
    def probability(self) -> float:
        """当前累积概率（0~1）。"""
        return self._p

    def tick(self, elapsed_sec: float = 60.0) -> bool:
        """累积一次，随机判定是否触发。``elapsed_sec`` 用于心跳实际间隔折算。"""
        steps = elapsed_sec / 60.0 if elapsed_sec > 0 else 1.0
        self._p = min(1.0, self._p + self._growth_rate * steps)
        if random.random() < self._p:
            self._p = self._initial_p
            return True
        return False

    def reset(self) -> None:
        """手动重置概率至初始值。"""
        self._p = self._initial_p
