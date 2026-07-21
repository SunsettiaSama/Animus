from __future__ import annotations

import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from ...contracts import FilledSegment
from .stream import NullSink, StreamEvent, StreamSink

StreamMode = Literal["typewriter", "immediate", "immediate_stream"]

# CJK/fullwidth pause marks via unicode escapes only
_PAUSE = "\uFF0C\u3002\uFF01\uFF1F\uFF1B\u3001\u2026,.!?;:\n"

_TOKEN_RE = re.compile(
    r"[\u4e00-\u9fff]"
    r"|[A-Za-z0-9]+(?:'[A-Za-z]+)?"
    r"|[" + re.escape(_PAUSE) + r"]"
    r"|."
)

_PAUSE_MARKS = frozenset(_PAUSE)


@dataclass(frozen=True)
class TypePace:
    """Type pace: delay ~= scale * sqrt(weight) * (1 + noise), clamped."""

    scale: float = 80.0
    jitter: float = 0.22
    min_ms: int = 18
    max_ms: int = 260
    seed: int | None = None


def tokenize(text: str) -> list[str]:
    body = text.strip()
    if not body:
        return []
    return [m.group(0) for m in _TOKEN_RE.finditer(body)]


def unit_weight(unit: str) -> float:
    if unit in _PAUSE_MARKS:
        return 2.4
    if len(unit) == 1 and "\u4e00" <= unit <= "\u9fff":
        return 1.0
    return max(0.6, min(3.0, 0.35 * len(unit)))


def rms_delay_ms(weight: float, pace: TypePace, rng: random.Random) -> int:
    base = pace.scale * (max(0.0, weight) ** 0.5)
    noise = 1.0 + pace.jitter * rng.gauss(0.0, 1.0)
    raw = base * max(0.35, noise)
    return max(pace.min_ms, min(pace.max_ms, int(round(raw))))


SleepFn = Callable[[float], None]


class ReplyStreamer:
    """Outbound push: think / token / done (typewriter | immediate | immediate_stream)."""

    def __init__(
        self,
        *,
        mode: StreamMode = "immediate",
        pace: TypePace | None = None,
        sink: StreamSink | None = None,
        sleep: SleepFn | None = None,
    ) -> None:
        self.mode: StreamMode = mode
        self.pace = pace or TypePace()
        self._sink = sink
        self._sleep = sleep or time.sleep
        self._rng = random.Random(self.pace.seed)
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def bind_sink(self, sink: StreamSink | None) -> None:
        self._sink = sink

    def set_pace(self, pace: TypePace) -> None:
        self.pace = pace
        self._rng = random.Random(pace.seed)

    def set_mode(self, mode: StreamMode) -> None:
        self.mode = mode

    def push(
        self,
        segments: tuple[FilledSegment, ...] | str,
        *,
        think: str = "",
        sink: StreamSink | None = None,
    ) -> str:
        self._busy = True
        target = sink or self._sink or NullSink()
        if isinstance(segments, str):
            body = segments.strip()
            parts = (body,) if body else ()
        else:
            parts = tuple(seg.text.strip() for seg in segments if seg.text.strip())
        answer = "\n".join(parts)

        target.on_event(StreamEvent(kind="think", text=think.strip(), index=0))

        if not answer:
            target.on_event(StreamEvent(kind="done", index=0))
            self._busy = False
            return ""

        if self.mode == "immediate":
            target.on_event(StreamEvent(kind="token", text=answer, index=0))
            target.on_event(StreamEvent(kind="done", index=1))
            self._busy = False
            return answer

        token_index = 0
        for part_i, part in enumerate(parts):
            if part_i > 0:
                target.on_event(StreamEvent(kind="token", text="\n", index=token_index))
                token_index += 1
            units = tokenize(part)
            if self.mode == "immediate_stream":
                for unit in units:
                    target.on_event(StreamEvent(kind="token", text=unit, index=token_index))
                    token_index += 1
                continue
            for unit in units:
                delay = rms_delay_ms(unit_weight(unit), self.pace, self._rng)
                if delay > 0:
                    self._sleep(delay / 1000.0)
                target.on_event(StreamEvent(kind="token", text=unit, index=token_index))
                token_index += 1

        target.on_event(StreamEvent(kind="done", index=token_index))
        self._busy = False
        return answer
