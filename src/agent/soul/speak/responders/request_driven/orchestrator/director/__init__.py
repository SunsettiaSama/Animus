from __future__ import annotations

from .decide import decide_plan
from .memory import apply_memory_requests, build_memory_inject_plan
from .service import ComposeDirector
from .share import attach_share_to_frame, build_share_compose_plan
from .store import DirectorPlanStore
from .types import (
    DirectorPlan,
    MemoryInjectPlan,
    ModuleDecision,
    ModuleSnapshot,
    ShareComposePlan,
)


def collect_snapshots(orchestrator, session_id: str, *, user_text: str = "", generation: int = 0):
    ctx = orchestrator.pipeline_context(
        session_id=session_id,
        user_text=user_text,
        generation=generation,
    )
    return orchestrator.block_registry.collect_snapshots(ctx.to_block_context())


__all__ = [
    "ComposeDirector",
    "DirectorPlan",
    "DirectorPlanStore",
    "MemoryInjectPlan",
    "ModuleDecision",
    "ModuleSnapshot",
    "ShareComposePlan",
    "apply_memory_requests",
    "attach_share_to_frame",
    "build_memory_inject_plan",
    "build_share_compose_plan",
    "collect_snapshots",
    "decide_plan",
]
