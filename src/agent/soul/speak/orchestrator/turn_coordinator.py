from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from .turn_inject_ledger import TurnInjectLedgerStore

if TYPE_CHECKING:
    from ..io.inbound.memory.compose_bridge import InboundMemoryComposeBridge
    from .director.types import DirectorPlan
    from .orchestrator import SpeakOrchestrator
    from .runner import SpeakComposeRunner

COMPOSE_INJECT_WAIT_MS = 300


TurnPriority = Literal["normal", "agent_open"]


@dataclass
class OrchestratorTurnState:
    session_id: str
    turn_index: int = 0
    user_text: str = ""
    refresh: dict[str, bool] = field(default_factory=dict)
    priority: TurnPriority = "normal"
    compose_waited_ms: int = 0
    compose_ready: bool = False
    kicked_at_monotonic: float = 0.0
    refresh_applied: dict[str, Any] = field(default_factory=dict)
    inject_ledger: dict[str, Any] = field(default_factory=dict)
    director_plan: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "refresh": dict(self.refresh),
            "priority": self.priority,
            "compose_waited_ms": self.compose_waited_ms,
            "compose_ready": self.compose_ready,
            "refresh_applied": dict(self.refresh_applied),
            "inject_ledger": dict(self.inject_ledger),
            "director_plan": dict(self.director_plan),
            "notes": list(self.notes),
        }


class OrchestratorTurnCoordinator:
    """用户入站：消费 DirectorPlan[i] + 并行生产 DirectorPlan[i+1]。"""

    def __init__(
        self,
        orchestrator: SpeakOrchestrator,
        *,
        compose_runner: SpeakComposeRunner,
        compose_wait_ms: int = COMPOSE_INJECT_WAIT_MS,
    ) -> None:
        self._orchestrator = orchestrator
        self._compose_runner = compose_runner
        self._compose_wait_ms = max(0, compose_wait_ms)
        self._states: dict[str, OrchestratorTurnState] = {}
        self._inject_ledgers = TurnInjectLedgerStore()
        self._lock = threading.Lock()

    @property
    def inject_ledgers(self) -> TurnInjectLedgerStore:
        return self._inject_ledgers

    @property
    def compose_director(self):
        return self._orchestrator.compose_director

    def state(self, session_id: str) -> OrchestratorTurnState:
        sid = session_id.strip()
        with self._lock:
            if sid not in self._states:
                self._states[sid] = OrchestratorTurnState(session_id=sid)
            return self._states[sid]

    def clear_session(self, session_id: str) -> None:
        sid = session_id.strip()
        self._states.pop(sid, None)
        self._inject_ledgers.clear_session(sid)

    def load_or_bootstrap_plan(
        self,
        session_id: str,
        *,
        turn_index: int,
        user_text: str,
        generation: int = 0,
    ) -> DirectorPlan:
        director = self.compose_director
        plan = director.load_plan(session_id, turn_index)
        if plan is not None:
            return plan
        meta = self._orchestrator.compose_cache(session_id).meta_snapshot()
        plan = director.bootstrap_plan(
            session_id,
            target_turn_index=turn_index,
            user_text=user_text,
            generation=generation,
            bundle_meta=meta,
        )
        director.save_plan(plan)
        return plan

    def kick_on_user_input(
        self,
        session_id: str,
        user_text: str,
        *,
        turn_index: int,
        memory_compose: InboundMemoryComposeBridge,
        generation: int = 0,
    ) -> OrchestratorTurnState:
        """路径 2.1：加载/兜底 plan[i]；路径 2.2：异步生产 plan[i+1]。"""
        sid = session_id.strip()
        state = self.state(sid)
        state.turn_index = turn_index
        state.user_text = user_text.strip()
        state.kicked_at_monotonic = time.monotonic()
        state.compose_ready = False
        state.compose_waited_ms = 0
        state.notes.append("turn_coordinator: kick on user input")

        plan = self.load_or_bootstrap_plan(
            sid,
            turn_index=turn_index,
            user_text=user_text,
            generation=generation,
        )
        state.director_plan = plan.snapshot()

        ledger = self._inject_ledgers.ledger(sid, turn_index)
        mem_notes = self.compose_director.apply_memory_kick(
            plan,
            memory_compose,
            user_text=user_text,
            ledger=ledger,
        )
        state.notes.extend(mem_notes)

        self._compose_runner.schedule_plan_warm(
            self._orchestrator,
            sid,
            target_turn_index=turn_index + 1,
            user_text=user_text,
            generation=generation,
        )

        state.refresh = plan.refresh_flags()
        state.refresh_applied = {
            "flags": dict(state.refresh),
            "notes": list(plan.notes),
        }
        state.inject_ledger = ledger.snapshot()
        state.notes.extend(plan.notes)
        return state

    def wait_before_compose(
        self,
        session_id: str,
        *,
        mode: str = "inbound",
        turn_index: int | None = None,
    ) -> OrchestratorTurnState:
        state = self.state(session_id)
        resolved_turn = turn_index if turn_index is not None else state.turn_index
        if self._compose_wait_ms > 0 and resolved_turn > 0:
            ready = self._compose_runner.wait_for_plan_ready(
                session_id,
                resolved_turn,
                timeout_ms=self._compose_wait_ms,
            )
            state.compose_ready = ready
            state.compose_waited_ms = self._compose_wait_ms
            if state.compose_ready:
                state.notes.append("turn_coordinator: compose plan ready within wait")
            else:
                state.notes.append("turn_coordinator: compose wait timeout, inject anyway")
        return state

    def plan_for_turn(self, session_id: str, turn_index: int) -> DirectorPlan | None:
        return self.compose_director.load_plan(session_id, turn_index)
