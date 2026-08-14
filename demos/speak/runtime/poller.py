from __future__ import annotations

import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from ..contracts import PollTickResult
from .clock import Clock
from .runner import SpeakDemoRunner

PollCurve = Literal["sqrt", "linear"]


@dataclass(frozen=True)
class PollSample:
    """一次骰子：是否对节奏导演发空闲轮询。"""

    check_index: int
    elapsed_sec: float
    probability: float
    sampled: bool
    curve: PollCurve = "sqrt"
    result: PollTickResult | None = None


def linear_decay_probability(
    elapsed_sec: float,
    *,
    horizon_sec: float,
    p_start: float,
    p_end: float,
) -> float:
    """线性衰减旁路：elapsed=0 → p_start；elapsed=horizon → p_end。"""
    if horizon_sec <= 0:
        return 0.0
    if elapsed_sec >= horizon_sec:
        return 0.0
    t = elapsed_sec / horizon_sec
    p = p_start + (p_end - p_start) * t
    return max(0.0, min(1.0, p))


def sqrt_decay_probability(
    elapsed_sec: float,
    *,
    horizon_sec: float,
    p_start: float,
    p_end: float,
) -> float:
    """
    根号衰减（默认）：p = p_end + (p_start - p_end) * √(1 - t)。

    前段概率掉得慢、后段掉得快，比线性更适合「别太早冷场、又别拖太久」。
    """
    if horizon_sec <= 0:
        return 0.0
    if elapsed_sec >= horizon_sec:
        return 0.0
    t = max(0.0, min(1.0, elapsed_sec / horizon_sec))
    p = p_end + (p_start - p_end) * math.sqrt(1.0 - t)
    return max(0.0, min(1.0, p))


def decay_probability(
    elapsed_sec: float,
    *,
    horizon_sec: float,
    p_start: float,
    p_end: float,
    curve: PollCurve = "sqrt",
) -> float:
    if curve == "linear":
        return linear_decay_probability(
            elapsed_sec,
            horizon_sec=horizon_sec,
            p_start=p_start,
            p_end=p_end,
        )
    return sqrt_decay_probability(
        elapsed_sec,
        horizon_sec=horizon_sec,
        p_start=p_start,
        p_end=p_end,
    )


class RhythmPoller:
    """
    衰减概率轮询：按 check 节拍掷骰，命中才问节奏导演。

    默认根号衰减；linear 为旁路。
    """

    def __init__(
        self,
        runner: SpeakDemoRunner,
        *,
        horizon_sec: float = 16.0,
        check_interval_sec: float = 1.0,
        p_start: float = 0.9,
        p_end: float = 0.0,
        max_checks: int = 0,
        seed: int | None = None,
        curve: PollCurve = "sqrt",
        clock: Clock | None = None,
        share_wants_fn: Callable[[], bool] | None = None,
        on_sample: Callable[[PollSample], None] | None = None,
    ) -> None:
        if not 0.0 <= p_end <= p_start <= 1.0:
            raise RuntimeError("poller: require 0 <= p_end <= p_start <= 1")
        if curve not in ("sqrt", "linear"):
            raise RuntimeError(f"poller: unknown curve {curve!r}")
        self._runner = runner
        self._horizon_sec = max(0.05, horizon_sec)
        self._check_interval_sec = max(0.05, check_interval_sec)
        self._p_start = float(p_start)
        self._p_end = float(p_end)
        self._max_checks = max(0, int(max_checks))
        self._curve: PollCurve = curve
        self._clock = clock or runner.clock
        self._share_wants_fn = share_wants_fn
        self._on_sample = on_sample
        self._rng = random.Random(seed)

    @property
    def curve(self) -> PollCurve:
        return self._curve

    def probability(self, elapsed_sec: float) -> float:
        return decay_probability(
            elapsed_sec,
            horizon_sec=self._horizon_sec,
            p_start=self._p_start,
            p_end=self._p_end,
            curve=self._curve,
        )

    def tick(self) -> PollTickResult:
        share_wants = False if self._share_wants_fn is None else bool(self._share_wants_fn())
        return self._runner.poll_once(share_wants=share_wants, deliver=True)

    def run(self) -> list[PollSample]:
        samples: list[PollSample] = []
        started = self._clock.now()
        check_index = 0
        while True:
            elapsed = self._clock.now() - started
            p = self.probability(elapsed)
            if p <= 0.0:
                break
            if self._max_checks > 0 and check_index >= self._max_checks:
                break

            self._clock.sleep(self._check_interval_sec)
            check_index += 1
            elapsed = self._clock.now() - started
            p = self.probability(elapsed)
            if p <= 0.0:
                break

            hit = self._rng.random() < p
            result = self.tick() if hit else None
            sample = PollSample(
                check_index=check_index,
                elapsed_sec=elapsed,
                probability=p,
                sampled=hit,
                curve=self._curve,
                result=result,
            )
            samples.append(sample)
            if self._on_sample is not None:
                self._on_sample(sample)
        return samples
