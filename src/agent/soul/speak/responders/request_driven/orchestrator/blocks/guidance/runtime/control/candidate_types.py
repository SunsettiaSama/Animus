from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SharePlannerCandidate:
    planner_index: int
    queue_index: int
    brief: str
    share_desire: str
    salience: float


@dataclass(frozen=True)
class RecallPlannerCandidate:
    planner_index: int
    unit_id: str
    line: str
