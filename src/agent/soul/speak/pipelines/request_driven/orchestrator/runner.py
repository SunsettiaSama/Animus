from __future__ import annotations

import threading
from collections import defaultdict

from agent.soul.workers import DomainWorker

from .orchestrator import SpeakOrchestrator
from .blocks.system.reply_style import SpeakReplyStyle
from .blocks.system.role import SpeakTurnMode


class SpeakComposeRunner:
    """后台 plan 预组装 worker：缓存 DirectorPlan.prepared_frame。"""

    def __init__(self, worker: DomainWorker | None = None) -> None:
        self._worker = worker or DomainWorker("speak-compose-worker")
        self._lock = threading.Lock()
        self._in_flight: set[tuple[str, int | str]] = set()
        self._generation: dict[str, int] = defaultdict(int)
        self._ready_events: dict[tuple[str, int], threading.Event] = {}
        self._last_orchestrator: SpeakOrchestrator | None = None
        self._last_turn_index: dict[str, int] = {}
        self._on_frame_ready = None

    @property
    def worker(self) -> DomainWorker:
        return self._worker

    def start(self) -> None:
        self._worker.start()

    def stop(self) -> None:
        self._worker.stop()
        with self._lock:
            self._in_flight.clear()
            self._ready_events.clear()

    def status(self) -> dict[str, object]:
        worker_status = self._worker.status()
        with self._lock:
            return {
                **worker_status,
                "plan_ready_events": len(self._ready_events),
                "in_flight": len(self._in_flight),
            }

    def invalidate(self, session_id: str) -> None:
        with self._lock:
            self._generation[session_id] += 1
            keys = [key for key in self._in_flight if key[0] == session_id]
            for key in keys:
                self._in_flight.discard(key)
            ready_keys = [key for key in self._ready_events if key[0] == session_id]
            for key in ready_keys:
                self._ready_events.pop(key, None)
            self._last_turn_index.pop(session_id, None)
        orch = self._last_orchestrator
        if orch is not None:
            orch.compose_director.clear_session(session_id)

    def _ready_event(self, session_id: str, turn_index: int) -> threading.Event:
        key = (session_id, turn_index)
        with self._lock:
            event = self._ready_events.get(key)
            if event is None:
                event = threading.Event()
                self._ready_events[key] = event
            return event

    def _signal_plan_ready(self, session_id: str, turn_index: int) -> None:
        self._ready_event(session_id, turn_index).set()

    def set_frame_ready_handler(self, handler) -> None:
        self._on_frame_ready = handler

    def schedule_plan_warm(
        self,
        orchestrator: SpeakOrchestrator,
        session_id: str,
        *,
        target_turn_index: int,
        user_text: str = "",
        generation: int = 0,
        mode: SpeakTurnMode = "inbound",
        reply_style: SpeakReplyStyle | None = None,
        agent_text: str = "",
    ) -> None:
        if self._worker.status()["state"] != "running":
            return
        sid = session_id.strip()
        inflight_key = (sid, target_turn_index)
        self._last_orchestrator = orchestrator
        self._last_turn_index[sid] = target_turn_index
        with self._lock:
            if inflight_key in self._in_flight:
                return
            self._in_flight.add(inflight_key)
            self._ready_event(sid, target_turn_index).clear()

        def _job() -> None:
            director = orchestrator.compose_director
            meta = orchestrator.compose_cache(sid).meta_snapshot()
            plan = director.produce_plan(
                sid,
                target_turn_index=target_turn_index,
                user_text=user_text,
                generation=generation,
                bundle_meta=meta,
                mode=mode,
                agent_text=agent_text,
            )
            director.save_plan(plan)
            if self._on_frame_ready is not None and plan.prepared_frame is not None:
                self._on_frame_ready(plan.prepared_frame, mode=mode)
            with self._lock:
                self._in_flight.discard(inflight_key)
            self._signal_plan_ready(sid, target_turn_index)

        self._worker.enqueue(_job)

    def schedule_director_build(
        self,
        orchestrator: SpeakOrchestrator,
        compose_director,
        session_id: str,
        *,
        target_turn_index: int,
        user_text: str,
        generation: int = 0,
        agent_text: str = "",
    ) -> None:
        self.schedule_plan_warm(
            orchestrator,
            session_id,
            target_turn_index=target_turn_index,
            user_text=user_text,
            generation=generation,
            agent_text=agent_text,
        )

    def wait_for_plan_ready(
        self,
        session_id: str,
        turn_index: int,
        *,
        timeout_ms: int = 300,
    ) -> bool:
        sid = session_id.strip()
        if timeout_ms > 0:
            self._ready_event(sid, turn_index).wait(timeout=timeout_ms / 1000.0)
        return True

