from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Union, TYPE_CHECKING

if TYPE_CHECKING:
    from plan.patch import HumanPatch


class PlanLifecycleState(str, Enum):
    idle       = "idle"
    planning   = "planning"     # PlannerAgent generating plan
    running    = "running"      # DAG tasks executing
    replanning = "replanning"   # ReplannerAgent triggered
    done       = "done"
    failed     = "failed"
    aborted    = "aborted"


@dataclass
class LifecycleStateEvent:
    plan_id: str
    state: str   # PlanLifecycleState value


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


@dataclass
class TaskStepEvent:
    plan_id: str
    task_id: str
    step: dict   # { type, index, thought, action, action_input, observation }


@dataclass
class PlannerStepEvent:
    plan_id: str
    phase: str         # "planning"
    step_index: int
    thought: str
    action: str
    observation: str


@dataclass
class ReplannerStartEvent:
    plan_id: str
    trigger: str
    cycle: int


@dataclass
class ReplannerCompleteEvent:
    plan_id: str
    decision: str      # done | continue | modify | abort
    reason: str
    patches_count: int


@dataclass
class ReplannerThinkingEvent:
    plan_id: str
    stage: str   # building_prompt | calling_llm | parsing
    cycle: int = 0


@dataclass
class NodeExpansionRequestEvent:
    plan_id: str
    task_id: str
    reason: str
    suggested_subtasks: list[str]


@dataclass
class LogLineEvent:
    plan_id: str
    level: str
    event: str
    payload: dict


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
    LifecycleStateEvent,
    TaskStepEvent,
    PlannerStepEvent,
    ReplannerStartEvent,
    ReplannerCompleteEvent,
    ReplannerThinkingEvent,
    NodeExpansionRequestEvent,
    LogLineEvent,
]
