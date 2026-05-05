from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union, TYPE_CHECKING

if TYPE_CHECKING:
    from plan.patch import HumanPatch


@dataclass
class PlanStartEvent:
    plan_id: str
    title: str
    task_count: int


@dataclass
class TaskStartEvent:
    plan_id: str
    task_id: str
    module: str
    profile: str


@dataclass
class TaskCompleteEvent:
    plan_id: str
    task_id: str
    result_preview: str    # truncated to 200 chars


@dataclass
class TaskFailedEvent:
    plan_id: str
    task_id: str
    error: str


@dataclass
class TaskSkippedEvent:
    plan_id: str
    task_id: str
    reason: str = ""


@dataclass
class TaskRunningEvent:
    plan_id: str
    task_id: str


@dataclass
class ReplanEvent:
    plan_id: str
    trigger: str
    decision: str
    patches_count: int
    cycle: int = 0


@dataclass
class HumanPatchEvent:
    plan_id: str
    patches_count: int
    patch_ops: list[str] = field(default_factory=list)


@dataclass
class SnapshotEvent:
    plan_id: str
    snapshot_id: str
    trigger: str


@dataclass
class PlanCompleteEvent:
    plan_id: str
    conclusion: str


@dataclass
class PlanAbortEvent:
    plan_id: str
    reason: str


PlanEvent = Union[
    PlanStartEvent,
    TaskStartEvent,
    TaskCompleteEvent,
    TaskFailedEvent,
    TaskSkippedEvent,
    TaskRunningEvent,
    ReplanEvent,
    HumanPatchEvent,
    SnapshotEvent,
    PlanCompleteEvent,
    PlanAbortEvent,
]
