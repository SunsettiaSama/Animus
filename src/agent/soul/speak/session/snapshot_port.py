from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from agent.soul.speak.pipelines.request_driven.orchestrator.state.core.types import (
    DialogueSnapshot,
    SessionRuntimeSnapshot,
    SessionSignals,
)

if TYPE_CHECKING:
    from agent.soul.speak.pipelines.request_driven.orchestrator.blocks.guidance import SpeakContextDistiller
    from agent.soul.speak.session import SpeakSessionService
    from agent.soul.speak.session.lifecycle.hold.registry import SpeakSessionRegistry


class RegistrySessionSnapshotPort:
    """session 侧只读快照端口：signals / runtime / dialogue。"""

    def __init__(
        self,
        registry: SpeakSessionRegistry,
        session_service: SpeakSessionService,
        *,
        context_distiller: SpeakContextDistiller | None = None,
        delivery_progress_fn: Callable[[str], tuple[int, int]] | None = None,
    ) -> None:
        self._registry = registry
        self._session_service = session_service
        self._context = context_distiller
        self._delivery_progress_fn = delivery_progress_fn

    def session_signals(self, session_id: str) -> SessionSignals:
        resolved = session_id.strip()
        record = self._registry.get(resolved)
        return SessionSignals(
            session_id=resolved,
            turn_index=self._registry.current_turn_index(resolved),
            generation=record.generation,
            interactor_id=self._registry.get_interactor(resolved),
        )

    def signals(self, session_id: str) -> SessionSignals:
        return self.session_signals(session_id)

    def runtime_snapshot(self, session_id: str) -> SessionRuntimeSnapshot:
        resolved = session_id.strip()
        queues = self._session_service.queues
        snap = queues.debug_snapshot(resolved)
        runtime = queues._runtime(resolved)
        with runtime.lock:
            typing = runtime.snapshot_typing()
            partial = runtime.partial_agent_output
            phase = runtime.phase
        segment_index = 0
        segment_total = 0
        if self._delivery_progress_fn is not None:
            segment_index, segment_total = self._delivery_progress_fn(resolved)
        return SessionRuntimeSnapshot(
            push_phase=str(snap.get("push_phase", phase)),
            partial_output_preview=partial[:300],
            current_segment_index=segment_index,
            segment_total=segment_total,
            typing_active=bool(typing.get("typing_active")),
            typing_idle=bool(typing.get("typing_idle")),
            draft_user_text=str(typing.get("draft_user_text", "")),
            brew_queue_depth=int(typing.get("brew_queue_depth", 0)),
            user_queue_pending=bool(snap.get("user_queue_pending")),
        )

    def dialogue_snapshot(
        self,
        session_id: str,
        *,
        user_text: str = "",
    ) -> DialogueSnapshot:
        resolved = session_id.strip()
        distill = ""
        wm = ""
        if self._context is not None:
            distill = self._context.context_distill_block(resolved)
            record = self._registry.get(resolved)
            wm = self._context.working_memory_block(
                resolved,
                generation=record.generation,
            )
        return DialogueSnapshot(
            user_text=user_text.strip(),
            context_distill=distill,
            working_memory=wm,
        )
