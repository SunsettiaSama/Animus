from __future__ import annotations

import threading
from collections import defaultdict

from collections.abc import Callable

from agent.soul.workers import DomainWorker

from .bundle import SpeakTurnMode
from .composer import SpeakPromptComposer
from .frame import PreparedComposeFrame
from .reply_style import SpeakReplyStyle

FrameReadyHandler = Callable[[PreparedComposeFrame, SpeakTurnMode], None]


class SpeakComposeRunner:
    """Speak compose 后台线程：预组装提示词帧，主路径非阻塞取用。"""

    def __init__(self, worker: DomainWorker | None = None) -> None:
        self._worker = worker or DomainWorker("speak-compose-worker")
        self._lock = threading.Lock()
        self._frames: dict[tuple[str, str], PreparedComposeFrame] = {}
        self._in_flight: set[tuple[str, str]] = set()
        self._generation: dict[str, int] = defaultdict(int)
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

    def schedule_prepare(
        self,
        composer: SpeakPromptComposer,
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

        style = reply_style or SpeakReplyStyle()

        def _job() -> None:
            frame = composer.prepare(
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
            if ready_handler is not None:
                ready_handler(frame, mode)

        self._worker.enqueue(_job)

    def take_ready_frame(
        self,
        session_id: str,
        *,
        mode: SpeakTurnMode = "inbound",
    ) -> PreparedComposeFrame | None:
        key = (session_id, mode)
        with self._lock:
            return self._frames.pop(key, None)
