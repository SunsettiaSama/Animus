from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from agent.soul.workers import DomainWorker

from .ingress import IngressEvent

if TYPE_CHECKING:
    from ..directors.coordinator import DirectorCoordinator
    from ..state import StateStore

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorThreadConfig:
    poll_check_ms: int = 200
    session_max_sec: float = 1800.0


class OrchestratorThread:
    """orchestrator 独立调度线程：事件队列、session 键控串行、生命周期。"""

    def __init__(
        self,
        *,
        state_store: StateStore,
        coordinator: DirectorCoordinator | None = None,
        on_delivery_ready: Callable[[str], None] | None = None,
        config: OrchestratorThreadConfig | None = None,
    ) -> None:
        self._state_store = state_store
        self._coordinator = coordinator
        self._on_delivery_ready = on_delivery_ready
        self._config = config or OrchestratorThreadConfig()
        self._worker = DomainWorker("speak-orchestrator-thread")
        self._session_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._poll_stop = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._active_sessions: set[str] = set()
        self._active_guard = threading.Lock()

    @property
    def state_store(self) -> StateStore:
        return self._state_store

    def bind_coordinator(self, coordinator: DirectorCoordinator) -> None:
        self._coordinator = coordinator

    def bind_delivery_ready(self, handler: Callable[[str], None]) -> None:
        self._on_delivery_ready = handler

    def start(self) -> None:
        self._worker.start()
        self._poll_stop.clear()
        if self._poll_thread is None or not self._poll_thread.is_alive():
            self._poll_thread = threading.Thread(
                target=self._poll_loop,
                name="speak-orchestrator-poll",
                daemon=True,
            )
            self._poll_thread.start()

    def stop(self) -> None:
        self._poll_stop.set()
        self._worker.stop()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=5.0)
            self._poll_thread = None

    def notify_user_input(
        self,
        session_id: str,
        user_text: str,
        *,
        turn_index: int,
    ) -> None:
        sid = session_id.strip()
        with self._active_guard:
            self._active_sessions.add(sid)
        event = IngressEvent(
            kind="user_input",
            session_id=sid,
            user_text=user_text.strip(),
            turn_index=turn_index,
        )
        self._enqueue_session(sid, lambda: self._handle_event(event))

    def submit_user_input_sync(
        self,
        session_id: str,
        user_text: str,
        *,
        turn_index: int,
        timeout_sec: float = 8.0,
    ):
        sid = session_id.strip()
        with self._active_guard:
            self._active_sessions.add(sid)
        event = IngressEvent(
            kind="user_input",
            session_id=sid,
            user_text=user_text.strip(),
            turn_index=turn_index,
        )
        lock = self._session_lock(sid)

        def _run():
            with lock:
                self._handle_event(event)
            state = self._state_store.session(sid)
            return state.pending_delivery_plan

        future = self._worker.submit(_run)
        return future.result(timeout=timeout_sec)

    def notify_session_close(self, session_id: str) -> None:
        sid = session_id.strip()
        event = IngressEvent(kind="session_close", session_id=sid)
        self._enqueue_session(sid, lambda: self._handle_event(event))

    def notify_delivery_done(self, session_id: str) -> None:
        sid = session_id.strip()
        event = IngressEvent(kind="delivery_done", session_id=sid)
        self._enqueue_session(sid, lambda: self._handle_event(event))

    def status(self) -> dict[str, Any]:
        worker_status = self._worker.status()
        with self._active_guard:
            active = sorted(self._active_sessions)
        return {
            "worker": worker_status,
            "active_sessions": active,
        }

    def _enqueue_session(self, session_id: str, task: Callable[[], None]) -> None:
        lock = self._session_lock(session_id)

        def _run() -> None:
            with lock:
                task()

        self._worker.enqueue(_run)

    def _session_lock(self, session_id: str) -> threading.Lock:
        sid = session_id.strip()
        with self._locks_guard:
            if sid not in self._session_locks:
                self._session_locks[sid] = threading.Lock()
            return self._session_locks[sid]

    def _handle_event(self, event: IngressEvent) -> None:
        if event.kind == "session_close":
            self._close_session(event.session_id)
            return
        if self._coordinator is None:
            return
        if event.kind == "user_input":
            self._coordinator.on_user_input(
                event.session_id,
                event.user_text,
                turn_index=event.turn_index,
            )
            self._maybe_notify_delivery(event.session_id)
            return
        if event.kind == "delivery_done":
            self._coordinator.on_delivery_done(event.session_id)
            return
        if event.kind == "poll_tick":
            self._coordinator.on_poll_tick(
                event.session_id,
                trigger=event.trigger,
            )
            self._maybe_notify_delivery(event.session_id)

    def _maybe_notify_delivery(self, session_id: str) -> None:
        if self._on_delivery_ready is None:
            return
        plan = self._state_store.take_pending_delivery_plan(session_id)
        if plan is None or plan.is_empty:
            return
        self._state_store.set_delivery_plan(session_id, plan)
        self._on_delivery_ready(session_id)

    def _close_session(self, session_id: str) -> None:
        sid = session_id.strip()
        with self._active_guard:
            self._active_sessions.discard(sid)
        self._state_store.clear_session(sid)
        with self._locks_guard:
            self._session_locks.pop(sid, None)

    def _poll_loop(self) -> None:
        while not self._poll_stop.is_set():
            now = time.monotonic()
            with self._active_guard:
                sessions = list(self._active_sessions)
            for sid in sessions:
                for trigger in ("append", "idle"):
                    cursor = self._state_store.poll_cursor(sid, trigger)
                    if cursor.is_session_expired():
                        self.notify_session_close(sid)
                        continue
                    if not cursor.armed:
                        continue
                    if cursor.next_fire_at <= 0:
                        cursor.schedule_next()
                        continue
                    if now >= cursor.next_fire_at:
                        cursor.armed = False
                        event = IngressEvent(
                            kind="poll_tick",
                            session_id=sid,
                            trigger=trigger,
                        )
                        self._enqueue_session(sid, lambda e=event: self._handle_event(e))
            time.sleep(self._config.poll_check_ms / 1000.0)
