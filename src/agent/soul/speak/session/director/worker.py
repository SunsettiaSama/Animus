from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from agent.soul.workers import DomainWorker

if TYPE_CHECKING:
    from .service import SessionDialogueDirector


@dataclass
class DirectorWorker:
    """按 session 串行调度导演触发，不阻塞 speak run_turn 主线程。"""

    worker: DomainWorker
    director: SessionDialogueDirector
    build_input: Callable[[str, str], object]
    collect_signals: Callable[[str], object]
    on_idle_complete: Callable[[str], None] | None = None

    def start_worker(self) -> None:
        self.worker.start()

    def stop_worker(self) -> None:
        self.worker.stop()

    def schedule_trigger(self, session_id: str, trigger: str) -> None:
        sid = session_id.strip()
        if not sid:
            return
        self.worker.submit(lambda: self._run(sid, trigger))

    def _run(self, session_id: str, trigger: str) -> None:
        session_input = self.build_input(session_id, trigger)
        signals = self.collect_signals(session_id)
        self.director.on_trigger(session_input, signals=signals)
        if trigger == "typing_idle" and self.on_idle_complete is not None:
            self.on_idle_complete(session_id)
