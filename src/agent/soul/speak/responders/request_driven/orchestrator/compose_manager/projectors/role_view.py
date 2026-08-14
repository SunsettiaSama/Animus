from __future__ import annotations

from dataclasses import dataclass, field

from ..domain.compress import TurnPair
from ..domain.retrieve import RetrieveHit


@dataclass(frozen=True)
class RoleContextView:
    """给 SpeakRole 的上下文视图；不含 wait/silence 语义。"""

    session_id: str
    history_distilled: tuple[str, ...] = ()
    working_turns: tuple[tuple[str, str], ...] = ()
    memory_texts: tuple[str, ...] = ()
    memory_ids: tuple[str, ...] = ()
    meta: dict[str, object] = field(default_factory=dict)


def build_role_context_view(
    session_id: str,
    *,
    distilled: list[str],
    working: list[TurnPair],
    hits: list[RetrieveHit],
    meta: dict[str, object] | None = None,
) -> RoleContextView:
    return RoleContextView(
        session_id=session_id.strip(),
        history_distilled=tuple(distilled),
        working_turns=tuple((p.user_text, p.agent_text) for p in working),
        memory_texts=tuple(hit.unit.text for hit in hits),
        memory_ids=tuple(hit.unit.unit_id for hit in hits),
        meta=dict(meta or {}),
    )
