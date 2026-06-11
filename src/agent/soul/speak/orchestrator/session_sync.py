from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .orchestrator import SpeakOrchestrator


def _default_submit(task: Callable[[], None]) -> None:
    thread = threading.Thread(target=task, daemon=True)
    thread.start()


class SessionComposeSyncAgent:
    """会话重连后异步对照 live 版本，向各子模块下发 refresh 指令。"""

    def __init__(
        self,
        orchestrator: SpeakOrchestrator,
        *,
        submit: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._submit = submit or _default_submit
        self._inflight: set[str] = set()
        self._lock = threading.Lock()

    def schedule(self, session_id: str) -> bool:
        sid = session_id.strip()
        if not sid:
            return False
        with self._lock:
            if sid in self._inflight:
                return False
            self._inflight.add(sid)
        self._submit(lambda: self._run(sid))
        return True

    def _run(self, session_id: str) -> None:
        port = self._orchestrator._session_port
        notes: list[str] = [f"session_compose_sync: start {session_id}"]
        if port is None:
            notes.append("session_compose_sync: no session port")
            self._finish(session_id, notes)
            return
        session = port.signals(session_id)
        notes.extend(
            self._orchestrator.compose_pipeline.sync_stale(
                session_id,
                generation=session.generation,
                turn_index=session.turn_index,
            )
        )
        self._finish(session_id, notes)

    def _finish(self, session_id: str, notes: list[str]) -> None:
        cache = self._orchestrator.compose_cache(session_id)
        cache.sync_notes.extend(notes)
        with self._lock:
            self._inflight.discard(session_id)
