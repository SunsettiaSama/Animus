from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from .compose_reconcile import build_compose_reconcile_plan
from .compose_slots import ComposeBlockId, KNOWN_COMPOSE_BLOCKS
from .module_refresh import apply_module_refresh
from .turn_inject_ledger import TurnInjectLedgerStore

if TYPE_CHECKING:
    from ..io.inbound.memory.compose_bridge import InboundMemoryComposeBridge
    from .orchestrator import SpeakOrchestrator
    from .runner import SpeakComposeRunner

COMPOSE_INJECT_WAIT_MS = 300


@dataclass(frozen=True)
class ModuleRefreshFlags:
    persona: bool = False
    scene: bool = False
    guidance: bool = False

    def snapshot(self) -> dict[str, bool]:
        return {
            "persona": self.persona,
            "scene": self.scene,
            "guidance": self.guidance,
        }


TurnPriority = Literal["normal", "agent_open"]


@dataclass
class OrchestratorTurnState:
    session_id: str
    turn_index: int = 0
    user_text: str = ""
    module_refresh: ModuleRefreshFlags = field(default_factory=ModuleRefreshFlags)
    priority: TurnPriority = "normal"
    compose_waited_ms: int = 0
    compose_ready: bool = False
    kicked_at_monotonic: float = 0.0
    module_refresh_applied: dict[str, Any] = field(default_factory=dict)
    inject_ledger: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "turn_index": self.turn_index,
            "module_refresh": self.module_refresh.snapshot(),
            "priority": self.priority,
            "compose_waited_ms": self.compose_waited_ms,
            "compose_ready": self.compose_ready,
            "module_refresh_applied": dict(self.module_refresh_applied),
            "inject_ledger": dict(self.inject_ledger),
            "notes": list(self.notes),
        }


class OrchestratorTurnCoordinator:
    """用户入站时立即触发编排注入；主路径仅短暂等待 compose，不阻塞 worker。"""

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

    def kick_on_user_input(
        self,
        session_id: str,
        user_text: str,
        *,
        turn_index: int,
        memory_compose: InboundMemoryComposeBridge,
        generation: int = 0,
    ) -> OrchestratorTurnState:
        """用户一发消息即注入：记忆/画像查询 + compose 预组装（不等待 agent 说完）。"""
        sid = session_id.strip()
        state = self.state(sid)
        state.turn_index = turn_index
        state.user_text = user_text.strip()
        state.kicked_at_monotonic = time.monotonic()
        state.compose_ready = False
        state.compose_waited_ms = 0
        state.notes.append("turn_coordinator: kick on user input")

        ledger = self._inject_ledgers.ledger(sid, turn_index)
        if not ledger.emergence_requested:
            memory_compose.request_emergence_query(
                sid,
                turn_index=turn_index,
                user_text=user_text,
            )
            ledger.emergence_requested = True
            ledger.notes.append("request_emergence")
        if not ledger.keyword_requested:
            memory_compose.request_keyword_query(
                sid,
                turn_index=turn_index,
                user_text=user_text,
            )
            ledger.keyword_requested = True
            ledger.notes.append("request_keyword")
        if not ledger.portrait_requested:
            memory_compose.request_interactor_portrait(
                sid,
                turn_index=turn_index,
                user_text=user_text,
            )
            ledger.portrait_requested = True
            ledger.notes.append("request_portrait")

        self._compose_runner.schedule_prepare(
            self._orchestrator,
            sid,
            mode="inbound",
            reply_style=None,
        )

        state.module_refresh = self._evaluate_module_refresh(sid, generation=generation)
        state.module_refresh_applied = apply_module_refresh(
            self._orchestrator,
            sid,
            state.module_refresh,
            generation=generation,
            turn_index=turn_index,
        )
        state.inject_ledger = ledger.snapshot()
        state.notes.extend(state.module_refresh_applied.get("notes", []))
        return state

    def wait_before_compose(
        self,
        session_id: str,
        *,
        mode: str = "inbound",
    ) -> OrchestratorTurnState:
        state = self.state(session_id)
        if self._compose_wait_ms > 0:
            ready = self._compose_runner.wait_for_frame_ready(
                session_id,
                mode=mode,
                timeout_ms=self._compose_wait_ms,
            )
            state.compose_ready = ready
            state.compose_waited_ms = self._compose_wait_ms
            if state.compose_ready:
                state.notes.append("turn_coordinator: compose frame ready within wait")
            else:
                state.notes.append("turn_coordinator: compose wait timeout, inject anyway")
        return state

    def _evaluate_module_refresh(
        self,
        session_id: str,
        *,
        generation: int,
    ) -> ModuleRefreshFlags:
        port = self._orchestrator._session_port
        if port is None:
            return ModuleRefreshFlags(persona=True, scene=True, guidance=True)
        session = port.signals(session_id)
        plan = build_compose_reconcile_plan(
            bundle_meta=self._orchestrator.compose_cache(session_id).meta_snapshot(),
            io=self._orchestrator.io,
            session=session,
        )
        flags = {block: False for block in KNOWN_COMPOSE_BLOCKS}
        for block in KNOWN_COMPOSE_BLOCKS:
            directive = plan.directive_for(block)
            flags[block] = directive.action == "refresh"
        return ModuleRefreshFlags(
            persona=flags.get("persona", False),
            scene=flags.get("scene", False),
            guidance=flags.get("guidance", False),
        )
