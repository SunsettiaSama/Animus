from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from ..core.types import (
    CURRENT_SCHEMA_VERSION,
    DialogueSnapshot,
    OrchestratorDomainSnapshot,
    SUPPORTED_SCHEMA_VERSIONS,
    SessionRuntimeSnapshot,
    SessionSignals,
    SessionSnapshot,
    build_snapshot_id,
    downgrade_snapshot,
)

if TYPE_CHECKING:
    from ..runtime.store import StateStore


class SessionSnapshotPort(Protocol):
    def session_signals(self, session_id: str) -> SessionSignals: ...

    def runtime_snapshot(self, session_id: str) -> SessionRuntimeSnapshot: ...

    def dialogue_snapshot(
        self,
        session_id: str,
        *,
        user_text: str = "",
    ) -> DialogueSnapshot: ...


class SnapshotBuilder:
    """从 SessionSnapshotPort 拉取 session 域数据并合并 orchestrator 调度态。"""

    def __init__(
        self,
        port: SessionSnapshotPort,
        *,
        state_store: StateStore | None = None,
        compose_meta_fn=None,
    ) -> None:
        self._port = port
        self._state_store = state_store
        self._compose_meta_fn = compose_meta_fn

    def build(
        self,
        session_id: str,
        *,
        user_text: str = "",
        schema_version: int = CURRENT_SCHEMA_VERSION,
    ) -> SessionSnapshot:
        sid = session_id.strip()
        signals = self._port.session_signals(sid)
        runtime = self._port.runtime_snapshot(sid)
        dialogue = self._port.dialogue_snapshot(sid, user_text=user_text)
        orchestrator = self._build_orchestrator_domain(sid)
        snapshot_id = build_snapshot_id(
            sid,
            turn_index=signals.turn_index,
            generation=signals.generation,
        )
        snapshot = SessionSnapshot(
            schema_version=schema_version,
            snapshot_id=snapshot_id,
            session_id=sid,
            signals=signals,
            runtime=runtime,
            dialogue=dialogue,
            orchestrator=orchestrator,
        )
        if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            return downgrade_snapshot(snapshot)
        return snapshot

    def _build_orchestrator_domain(self, session_id: str) -> OrchestratorDomainSnapshot:
        compose_meta: dict[str, Any] = {}
        if self._compose_meta_fn is not None:
            compose_meta = dict(self._compose_meta_fn(session_id) or {})
        director_decisions: dict[str, Any] = {}
        pending_plan_id = ""
        if self._state_store is not None:
            state = self._state_store.session(session_id)
            director_decisions = dict(state.director_cache)
            plan = state.pending_delivery_plan or state.delivery_plan
            if plan is not None:
                pending_plan_id = plan.plan_id
        return OrchestratorDomainSnapshot(
            compose_meta=compose_meta,
            director_decisions=director_decisions,
            pending_delivery_plan_id=pending_plan_id,
        )
