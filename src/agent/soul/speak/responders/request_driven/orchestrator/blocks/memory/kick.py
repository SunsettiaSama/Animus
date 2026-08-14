from __future__ import annotations

from ...director.types import MemoryInjectPlan


def kick_memory_requests(
    memory_compose,
    session_id: str,
    *,
    turn_index: int,
    user_text: str,
    plan: MemoryInjectPlan,
    ledger,
) -> list[str]:
    notes: list[str] = []
    if plan.request_emergence and not ledger.emergence_requested:
        memory_compose.request_emergence_query(
            session_id,
            turn_index=turn_index,
            user_text=user_text,
        )
        ledger.emergence_requested = True
        notes.append("director_memory: request_emergence")
    if plan.request_keyword and not ledger.keyword_requested:
        memory_compose.request_keyword_query(
            session_id,
            turn_index=turn_index,
            user_text=user_text,
        )
        ledger.keyword_requested = True
        notes.append("director_memory: request_keyword")
    if plan.request_portrait and not ledger.portrait_requested:
        memory_compose.request_interactor_portrait(
            session_id,
            turn_index=turn_index,
            user_text=user_text,
        )
        ledger.portrait_requested = True
        notes.append("director_memory: request_portrait")
    return notes
