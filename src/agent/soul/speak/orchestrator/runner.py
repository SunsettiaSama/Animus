from __future__ import annotations

import threading
from collections import defaultdict

from collections.abc import Callable

from agent.soul.workers import DomainWorker

from .orchestrator import SpeakOrchestrator
from .frame import PreparedComposeFrame
from .system.reply_style import SpeakReplyStyle
from .system.role import SpeakTurnMode

FrameReadyHandler = Callable[[PreparedComposeFrame, SpeakTurnMode], None]


class SpeakComposeRunner:
    """后台预组装 worker：非阻塞缓存 PreparedComposeFrame。"""

    def __init__(self, worker: DomainWorker | None = None) -> None:
        self._worker = worker or DomainWorker("speak-compose-worker")
        self._lock = threading.Lock()
        self._frames: dict[tuple[str, str], PreparedComposeFrame] = {}
        self._in_flight: set[tuple[str, str]] = set()
        self._generation: dict[str, int] = defaultdict(int)
        self._ready_events: dict[tuple[str, str], threading.Event] = {}
        self._on_frame_ready: FrameReadyHandler | None = None

    def set_frame_ready_handler(self, handler: FrameReadyHandler | None) -> None:
        self._on_frame_ready = handler

    @property
    def worker(self) -> DomainWorker:
        return self._worker

    def start(self) -> None:
        self._worker.start()

    def stop(self) -> None:
        self._worker.stop()
        with self._lock:
            self._frames.clear()
            self._in_flight.clear()

    def status(self) -> dict[str, object]:
        worker_status = self._worker.status()
        with self._lock:
            return {
                **worker_status,
                "cached_frames": len(self._frames),
                "in_flight": len(self._in_flight),
            }

    def invalidate(self, session_id: str) -> None:
        with self._lock:
            self._generation[session_id] += 1
            keys = [key for key in self._frames if key[0] == session_id]
            for key in keys:
                del self._frames[key]
            inflight = [key for key in self._in_flight if key[0] == session_id]
            for key in inflight:
                self._in_flight.discard(key)
            ready_keys = [key for key in self._ready_events if key[0] == session_id]
            for key in ready_keys:
                self._ready_events.pop(key, None)

    def _ready_event(self, session_id: str, mode: SpeakTurnMode) -> threading.Event:
        key = (session_id, mode)
        with self._lock:
            event = self._ready_events.get(key)
            if event is None:
                event = threading.Event()
                self._ready_events[key] = event
            return event

    def _signal_frame_ready(self, session_id: str, mode: SpeakTurnMode) -> None:
        self._ready_event(session_id, mode).set()

    def schedule_prepare(
        self,
        orchestrator: SpeakOrchestrator,
        session_id: str,
        *,
        mode: SpeakTurnMode = "inbound",
        reply_style: SpeakReplyStyle | None = None,
    ) -> None:
        if self._worker.status()["state"] != "running":
            return
        key = (session_id, mode)
        with self._lock:
            generation = self._generation[session_id]
            if key in self._in_flight:
                return
            self._in_flight.add(key)
            self._ready_event(session_id, mode).clear()

        style = reply_style or SpeakReplyStyle()

        def _job() -> None:
            frame = orchestrator.prepare(
                session_id,
                mode=mode,
                reply_style=style,
                generation=generation,
            )
            with self._lock:
                self._in_flight.discard(key)
                if self._generation[session_id] != generation:
                    return
                self._frames[key] = frame
                ready_handler = self._on_frame_ready
            self._signal_frame_ready(session_id, mode)
            if ready_handler is not None:
                ready_handler(frame, mode)

    def wait_for_frame_ready(
        self,
        session_id: str,
        *,
        mode: SpeakTurnMode = "inbound",
        timeout_ms: int = 300,
    ) -> bool:
        key = (session_id, mode)
        if timeout_ms > 0:
            self._ready_event(session_id, mode).wait(timeout=timeout_ms / 1000.0)
        with self._lock:
            return key in self._frames

        self._worker.enqueue(_job)

    def take_ready_frame(
        self,
        session_id: str,
        *,
        mode: SpeakTurnMode = "inbound",
    ) -> PreparedComposeFrame | None:
        key = (session_id, mode)
        with self._lock:
            frame = self._frames.pop(key, None)
        if frame is not None:
            self._ready_event(session_id, mode).clear()
        return frame
