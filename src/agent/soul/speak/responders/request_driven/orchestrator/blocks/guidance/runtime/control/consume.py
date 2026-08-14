from __future__ import annotations

from collections.abc import Callable

from .candidate_types import RecallPlannerCandidate, SharePlannerCandidate
from .state import GuidanceControlState


def resolve_emit_share_queue_index(
    emit_planner_index: int | None,
    candidates: tuple[SharePlannerCandidate, ...],
) -> int | None:
    if emit_planner_index is None:
        return None
    for item in candidates:
        if item.planner_index == emit_planner_index:
            return item.queue_index
    return None


def resolve_emit_recall_unit_id(
    emit_planner_index: int | None,
    candidates: tuple[RecallPlannerCandidate, ...],
) -> str | None:
    if emit_planner_index is None:
        return None
    for item in candidates:
        if item.planner_index == emit_planner_index:
            return item.unit_id
    return None


def consume_guidance_emits(
    session_id: str,
    state: GuidanceControlState,
    *,
    pop_presence_share_at: Callable[[str, int], bool] | None = None,
    pop_session_share_at: Callable[[str, int], bool] | None = None,
    use_session_share_queue: bool = False,
    mark_recall_unit_consumed: Callable[[str, str], None] | None = None,
) -> list[str]:
    notes: list[str] = []
    queue_index = state.emit_share_queue_index
    if queue_index is not None:
        pop_fn = pop_session_share_at if use_session_share_queue else pop_presence_share_at
        if pop_fn is None:
            notes.append(f"share consume skipped: no pop port queue_index={queue_index}")
        elif pop_fn(session_id, queue_index):
            notes.append(f"share consumed queue_index={queue_index}")
        else:
            notes.append(f"share consume failed queue_index={queue_index}")

    unit_id = state.emit_recall_unit_id
    if unit_id and mark_recall_unit_consumed is not None:
        mark_recall_unit_consumed(session_id, unit_id)
        notes.append(f"recall consumed unit_id={unit_id}")
    return notes
