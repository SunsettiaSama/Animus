from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ContextView:
    session_id: str
    history_distilled: tuple[str, ...] = ()
    working_turns: tuple[tuple[str, str], ...] = ()
    memory_hits: tuple[tuple[str, str, float, str], ...] = ()
    meta: dict[str, object] = field(default_factory=dict)


class ContextViewProvider(Protocol):
    def project(
        self,
        session_id: str,
        *,
        user_text: str = "",
    ) -> ContextView: ...
