from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

CURRENT_SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS: frozenset[int] = frozenset(
    {CURRENT_SCHEMA_VERSION, CURRENT_SCHEMA_VERSION - 1},
)


@dataclass(frozen=True)
class SessionSignals:
    session_id: str
    turn_index: int
    generation: int
    interactor_id: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "generation": self.generation,
            "interactor_id": self.interactor_id,
        }


@dataclass(frozen=True)
class SessionRuntimeSnapshot:
    push_phase: str = "idle"
    partial_output_preview: str = ""
    current_segment_index: int = 0
    segment_total: int = 0
    typing_active: bool = False
    typing_idle: bool = True
    draft_user_text: str = ""
    brew_queue_depth: int = 0
    user_queue_pending: bool = False

    def snapshot(self) -> dict[str, Any]:
        return {
            "push_phase": self.push_phase,
            "partial_output_preview": self.partial_output_preview,
            "current_segment_index": self.current_segment_index,
            "segment_total": self.segment_total,
            "typing_active": self.typing_active,
            "typing_idle": self.typing_idle,
            "draft_user_text": self.draft_user_text,
            "brew_queue_depth": self.brew_queue_depth,
            "user_queue_pending": self.user_queue_pending,
        }


@dataclass(frozen=True)
class DialogueSnapshot:
    user_text: str = ""
    context_distill: str = ""
    working_memory: str = ""
    recent_turns: tuple[str, ...] = ()

    def snapshot(self) -> dict[str, Any]:
        return {
            "user_text": self.user_text,
            "context_distill": self.context_distill,
            "working_memory": self.working_memory,
            "recent_turns": list(self.recent_turns),
        }


@dataclass(frozen=True)
class OrchestratorDomainSnapshot:
    compose_meta: dict[str, Any] = field(default_factory=dict)
    director_decisions: dict[str, Any] = field(default_factory=dict)
    pending_delivery_plan_id: str = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "compose_meta": dict(self.compose_meta),
            "director_decisions": dict(self.director_decisions),
            "pending_delivery_plan_id": self.pending_delivery_plan_id,
        }


@dataclass(frozen=True)
class SessionSnapshot:
    schema_version: int
    snapshot_id: str
    session_id: str
    signals: SessionSignals
    runtime: SessionRuntimeSnapshot
    dialogue: DialogueSnapshot
    orchestrator: OrchestratorDomainSnapshot = field(
        default_factory=OrchestratorDomainSnapshot,
    )
    captured_at: float = field(default_factory=time.monotonic)

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "snapshot_id": self.snapshot_id,
            "session_id": self.session_id,
            "signals": self.signals.snapshot(),
            "runtime": self.runtime.snapshot(),
            "dialogue": self.dialogue.snapshot(),
            "orchestrator": self.orchestrator.snapshot(),
            "captured_at": self.captured_at,
        }


def build_snapshot_id(
    session_id: str,
    *,
    turn_index: int,
    generation: int,
) -> str:
    ts = int(time.time() * 1000)
    return f"{session_id.strip()}:{turn_index}:{generation}:{ts}"


def downgrade_snapshot(snapshot: SessionSnapshot) -> SessionSnapshot:
    """低于 current-1 版本时走最小字段降级路径。"""
    return SessionSnapshot(
        schema_version=CURRENT_SCHEMA_VERSION - 1,
        snapshot_id=snapshot.snapshot_id,
        session_id=snapshot.session_id,
        signals=snapshot.signals,
        runtime=SessionRuntimeSnapshot(
            push_phase=snapshot.runtime.push_phase,
            partial_output_preview=snapshot.runtime.partial_output_preview[:120],
        ),
        dialogue=DialogueSnapshot(user_text=snapshot.dialogue.user_text),
    )
