from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

TimelineOpKind = Literal["think", "wait", "emit", "silence", "body"]


@dataclass(frozen=True)
class TimelineOp:
    kind: TimelineOpKind
    seconds: float = 0.0
    texts: tuple[str, ...] = ()
    body: str = ""
    meta: dict[str, object] = field(default_factory=dict)

    @property
    def wait_ms(self) -> int:
        return max(0, int(round(self.seconds * 1000.0)))


@dataclass(frozen=True)
class RoleTimeline:
    ops: tuple[TimelineOp, ...] = ()
    ignored: tuple[str, ...] = ()

    @property
    def spoken_texts(self) -> tuple[str, ...]:
        out: list[str] = []
        for op in self.ops:
            if op.kind == "emit":
                out.extend(t for t in op.texts if t.strip())
        return tuple(out)

    @property
    def answer_text(self) -> str:
        return "".join(self.spoken_texts)
