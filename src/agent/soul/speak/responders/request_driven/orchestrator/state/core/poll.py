from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any, Literal

PollTrigger = Literal["append", "idle", "interrupt"]

# 用户回合后的临时抽样名义间隔：第2拍~5s，第3拍~15s，第4拍~30s，其后爬升
DEFAULT_LADDER_SEC: tuple[float, ...] = (5.0, 15.0, 30.0, 60.0, 90.0, 120.0)


@dataclass(frozen=True)
class PollFrameDecision:
    """一帧到期后的抽样结果。"""

    frame: int
    execute: bool
    t_sec: float
    p_fire: float
    quiet_elapsed_sec: float
    skipped: bool
    ladder_step: int = 0


@dataclass
class PollFrameManager:
    """轮询帧数管理器：用户入站为第1拍（即时，不经本管理器）；之后按阶梯抽 t。

    阶梯（临时名义值，带 jitter）：5s → 15s → 30s → 60s → 90s → 120s。
    层 1 — X：是否执行；靠后的阶梯 p_fire 更低。
    层 2 — t：当前阶梯名义值 × (1±jitter)。

    节奏表 due unit 不得绕过本管理器强制开拍；只在已到期的帧上检查 handoff。
    """

    session_id: str
    trigger: PollTrigger = "idle"
    frame_index: int = 0
    ladder_sec: tuple[float, ...] = DEFAULT_LADDER_SEC
    ladder_step: int = 0
    jitter_ratio: float = 0.2
    min_t_sec: float = 3.0
    max_t_sec: float = 120.0
    p_floor: float = 0.12
    armed: bool = False
    next_fire_at: float = 0.0
    last_t_sec: float = 0.0
    last_p_fire: float = 1.0
    last_execute: bool | None = None
    quiet_anchor: float = field(default_factory=time.monotonic)
    session_opened_at: float = field(default_factory=time.monotonic)
    session_max_sec: float = 1800.0
    notes: list[str] = field(default_factory=list)
    _first_schedule: bool = True
    _rng: random.Random = field(default_factory=random.Random, repr=False)

    @property
    def k(self) -> int:
        return self.frame_index

    @k.setter
    def k(self, value: int) -> None:
        self.frame_index = int(value)

    @property
    def base_ms(self) -> int:
        return int(round(self._nominal_t() * 1000.0))

    @property
    def max_ms(self) -> int:
        return int(round(self.max_t_sec * 1000.0))

    def quiet_elapsed_sec(self, *, now: float | None = None) -> float:
        current = now if now is not None else time.monotonic()
        return max(0.0, current - float(self.quiet_anchor))

    def _ladder(self) -> tuple[float, ...]:
        raw = self.ladder_sec or DEFAULT_LADDER_SEC
        return tuple(float(x) for x in raw if float(x) > 0) or DEFAULT_LADDER_SEC

    def _step_index(self) -> int:
        ladder = self._ladder()
        return min(max(0, int(self.ladder_step)), len(ladder) - 1)

    def _nominal_t(self) -> float:
        ladder = self._ladder()
        return float(ladder[self._step_index()])

    def p_fire(self, *, now: float | None = None) -> float:
        """靠前的阶梯几乎必执行；越往后越易跳过。"""
        del now
        floor = max(0.0, min(1.0, float(self.p_floor)))
        step = self._step_index()
        return max(floor, min(1.0, 1.0 - 0.12 * float(step)))

    def sample_t(self, *, now: float | None = None) -> float:
        """按当前阶梯名义值做临时 jitter 抽样。"""
        del now
        nominal = self._nominal_t()
        j = max(0.0, min(0.9, float(self.jitter_ratio)))
        lo = nominal * (1.0 - j)
        hi = nominal * (1.0 + j)
        u = self._rng.random()
        t = lo + (hi - lo) * u
        t_min = max(0.05, float(self.min_t_sec))
        t_max = max(t_min, float(self.max_t_sec))
        return min(t_max, max(t_min, t))

    def interval_ms(self) -> int:
        if self.last_t_sec > 0:
            return int(round(self.last_t_sec * 1000.0))
        return int(round(self._nominal_t() * 1000.0))

    def is_session_expired(self) -> bool:
        elapsed = time.monotonic() - self.session_opened_at
        return elapsed >= self.session_max_sec

    def schedule_next(self, *, advance: bool | None = None) -> None:
        """预约下一帧。默认：用户周期内首次不升阶，之后每次升一阶。"""
        if advance is None:
            advance = not self._first_schedule
        if advance:
            ladder = self._ladder()
            self.ladder_step = min(int(self.ladder_step) + 1, len(ladder) - 1)
        self._first_schedule = False
        t = self.sample_t()
        self.last_t_sec = t
        self.next_fire_at = time.monotonic() + t
        self.armed = True

    def take_due_frame(self, *, now: float | None = None) -> PollFrameDecision:
        """帧到期：抽 X；跳过则同阶重约；执行则卸武装等业务回补。"""
        current = now if now is not None else time.monotonic()
        quiet = self.quiet_elapsed_sec(now=current)
        p = self.p_fire(now=current)
        execute = self._rng.random() < p
        self.frame_index += 1
        self.last_p_fire = p
        self.last_execute = execute
        step = self._step_index()
        t_for_note = self.last_t_sec
        if not execute:
            self.schedule_next(advance=False)
            t_for_note = self.last_t_sec
            self.notes.append(
                f"frame={self.frame_index} step={step} skip p_fire={p:.3f} next_t={t_for_note:.2f}s"
            )
            return PollFrameDecision(
                frame=self.frame_index,
                execute=False,
                t_sec=t_for_note,
                p_fire=p,
                quiet_elapsed_sec=quiet,
                skipped=True,
                ladder_step=step,
            )
        self.armed = False
        self.next_fire_at = 0.0
        self.notes.append(f"frame={self.frame_index} step={step} fire p_fire={p:.3f}")
        return PollFrameDecision(
            frame=self.frame_index,
            execute=True,
            t_sec=t_for_note if t_for_note > 0 else self._nominal_t(),
            p_fire=p,
            quiet_elapsed_sec=quiet,
            skipped=False,
            ladder_step=step,
        )

    def reset_decay(self) -> None:
        """用户新入站：静默与阶梯归零（第1拍由 ingress 即时响应，不经本管理器）。"""
        self.frame_index = 0
        self.ladder_step = 0
        self._first_schedule = True
        self.quiet_anchor = time.monotonic()
        self.next_fire_at = 0.0
        self.last_t_sec = 0.0
        self.last_p_fire = 1.0
        self.last_execute = None
        self.armed = False

    def reset(self) -> None:
        self.reset_decay()
        self.session_opened_at = time.monotonic()

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "trigger": self.trigger,
            "frame": self.frame_index,
            "k": self.frame_index,
            "ladder_step": self.ladder_step,
            "ladder_sec": list(self._ladder()),
            "nominal_t_sec": self._nominal_t(),
            "min_t_sec": self.min_t_sec,
            "max_t_sec": self.max_t_sec,
            "interval_ms": self.interval_ms(),
            "last_t_sec": self.last_t_sec,
            "p_fire": self.p_fire(),
            "last_p_fire": self.last_p_fire,
            "last_execute": self.last_execute,
            "quiet_elapsed_sec": self.quiet_elapsed_sec(),
            "armed": self.armed,
            "next_fire_at": self.next_fire_at,
            "session_expired": self.is_session_expired(),
            "notes": list(self.notes[-8:]),
        }
