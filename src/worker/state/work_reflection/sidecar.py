"""Work-reflection state sidecar, parallel to memory_distill."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any

from worker.state.schema import AgentStateSnapshot, ReflectionPortraitState
from worker.state.store import AgentStateStore
from worker.state.work_reflection.reflection import ReflectionAgent, ReflectionTurn
from worker.state.work_reflection.task_graph import TurnTaskGraph

logger = logging.getLogger(__name__)

SIDECAR_ID = "work_reflection"


@dataclass
class WorkerTurnState:
    snapshot: AgentStateSnapshot
    task_graph: TurnTaskGraph


class WorkReflectionSidecar:
    """Owns the complete begin-turn → graph → reflect lifecycle."""

    sidecar_id = SIDECAR_ID

    def __init__(
        self,
        store: AgentStateStore,
        *,
        llm: Any | None,
        task_runner: Any | None,
    ) -> None:
        self._store = store
        self._llm = llm
        self._task_runner = task_runner
        self._reflection_lock = threading.Lock()

    def bind_llm(self, llm: Any | None) -> None:
        self._llm = llm

    def bind_task_runner(self, task_runner: Any | None) -> None:
        self._task_runner = task_runner

    def begin_turn(self, question: str) -> WorkerTurnState:
        return WorkerTurnState(
            snapshot=self._store.snapshot(),
            task_graph=TurnTaskGraph(question, max_chars=500),
        )

    def reflect(
        self,
        *,
        question: str,
        answer: str,
        steps: tuple[dict, ...],
        task_graph: str,
        terminal_status: str,
        units: tuple[dict, ...] | None = None,
    ) -> ReflectionPortraitState:
        if self._llm is None:
            return self._store.snapshot().reflection_portrait
        turn = ReflectionTurn(
            question=question,
            answer=answer,
            steps=steps,
            task_graph=task_graph,
            terminal_status=terminal_status,
            units=units or (),
        )
        with self._reflection_lock:
            candidate = ReflectionAgent(self._llm).revise(
                self._store.snapshot(),
                turn,
            )
            self._store.commit(candidate)
        logger.info(
            "[worker.state.work_reflection] committed turn_count=%d",
            candidate.turn_count,
        )
        return candidate

    def submit_reflection(
        self,
        *,
        question: str,
        answer: str,
        steps: tuple[dict, ...],
        task_graph: str,
        terminal_status: str,
        units: tuple[dict, ...] | None = None,
    ) -> Any | None:
        def job() -> ReflectionPortraitState:
            return self.reflect(
                question=question,
                answer=answer,
                steps=steps,
                task_graph=task_graph,
                terminal_status=terminal_status,
                units=units,
            )

        if self._task_runner is None:
            return job()

        def on_error(exc: BaseException) -> None:
            logger.error("[worker.state.work_reflection] failed: %s", exc)

        return self._task_runner.submit(
            "worker_state_work_reflection",
            job,
            on_error=on_error,
        )