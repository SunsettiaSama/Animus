from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

OutboundOpKind = Literal["think", "wait", "silence", "speak", "action", "finish"]


@dataclass(frozen=True)
class OutboundOp:
    kind: OutboundOpKind
    text: str = ""
    seconds: float = 0.0
    final: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OutboundRequest:
    session_id: str
    ops: tuple[OutboundOp, ...] = ()
    user_text: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def answer_text(self) -> str:
        parts = [op.text.strip() for op in self.ops if op.kind == "speak" and op.text.strip()]
        return "".join(parts)
