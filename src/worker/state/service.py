"""Facade for persistent portraits and per-request Worker state."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from worker.state.memory_distill import CHAIN_ID as MEMORY_DISTILL_CHAIN_ID
from worker.state.memory_distill import MemoryDistillChain
from worker.state.memory_distill.deps import (
    build_medium_reader,
    resolve_hybrid_query,
    resolve_memory_port,
    resolve_persona_revision,
    resolve_stable_anchor,
)
from worker.state.schema import (
    MEMORY_PORTRAIT_SLOT,
    AgentStateSnapshot,
    ChainResult,
    ReflectionPortraitState,
    StateSlot,
)
from worker.state.store import AgentStateStore
from worker.state.work_reflection import (
    SIDECAR_ID as WORK_REFLECTION_SIDECAR_ID,
    WorkReflectionSidecar,
    WorkerTurnState,
)

logger = logging.getLogger(__name__)


class AgentStateService:
    """Facade over parallel memory_distill and work_reflection sidecars."""

    MEMORY_DISTILL_CHAIN_ID = MEMORY_DISTILL_CHAIN_ID
    WORK_REFLECTION_SIDECAR_ID = WORK_REFLECTION_SIDECAR_ID

    def __init__(
        self,
        *,
        state_dir: str | Path,
        llm: Any | None = None,
        soul: Any | None = None,
        medium_dir: str | Path | None = None,
        task_runner: Any | None = None,
    ) -> None:
        self._store = AgentStateStore(state_dir)
        self._llm = llm
        self._soul = soul
        self._medium_dir = medium_dir
        self._task_runner = task_runner
        self._work_reflection = WorkReflectionSidecar(
            self._store,
            llm=llm,
            task_runner=task_runner,
        )
        if not self._store.path.is_file():
            self._store.save()

    @property
    def store(self) -> AgentStateStore:
        return self._store

    def bind_llm(self, llm: Any | None) -> None:
        self._llm = llm
        self._work_reflection.bind_llm(llm)

    def bind_soul(self, soul: Any | None) -> None:
        self._soul = soul

    def bind_task_runner(self, task_runner: Any | None) -> None:
        self._task_runner = task_runner
        self._work_reflection.bind_task_runner(task_runner)

    def read(self, slot_type: str) -> StateSlot | None:
        return self._store.read(slot_type)

    def snapshot(self) -> AgentStateSnapshot:
        return self._store.snapshot()

    def begin_turn(self, question: str) -> WorkerTurnState:
        return self._work_reflection.begin_turn(question)

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
        return self._work_reflection.reflect(
            question=question,
            answer=answer,
            steps=steps,
            task_graph=task_graph,
            terminal_status=terminal_status,
            units=units,
        )

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
        return self._work_reflection.submit_reflection(
            question=question,
            answer=answer,
            steps=steps,
            task_graph=task_graph,
            terminal_status=terminal_status,
            units=units,
        )
    def _memory_chain(
        self,
        *,
        worker_unit_lines: list[str] | tuple[str, ...] | None = None,
    ) -> MemoryDistillChain:
        if self._llm is None:
            raise RuntimeError("memory_distill requires llm")
        return MemoryDistillChain(
            self._store,
            llm=self._llm,
            memory=resolve_memory_port(self._soul),
            medium=build_medium_reader(self._medium_dir),
            persona_revision=resolve_persona_revision(self._soul),
            stable_anchor=resolve_stable_anchor(self._soul),
            hybrid_query=resolve_hybrid_query(self._soul),
            worker_unit_lines=worker_unit_lines,
        )

    def refresh_fallback(
        self,
        *,
        force: bool = False,
        unit_summary: list[str] | tuple[str, ...] | None = None,
    ) -> ChainResult:
        if self._llm is None:
            return ChainResult(
                self._store.read(MEMORY_PORTRAIT_SLOT),
                False,
                "no_llm",
            )
        return self._memory_chain(worker_unit_lines=unit_summary).run(force=force)

    def submit_refresh_fallback(
        self,
        *,
        force: bool = False,
        unit_summary: list[str] | tuple[str, ...] | None = None,
    ) -> Any | None:
        def job() -> ChainResult:
            return self.refresh_fallback(force=force, unit_summary=unit_summary)

        if self._task_runner is None:
            return job()

        def on_error(exc: BaseException) -> None:
            logger.error("[worker.state.memory_distill] failed: %s", exc)

        return self._task_runner.submit(
            f"worker_state_{MEMORY_DISTILL_CHAIN_ID}",
            job,
            on_error=on_error,
        )

def build_agent_state_service(
    *,
    state_dir: str | Path,
    llm: Any | None = None,
    soul: Any | None = None,
    medium_dir: str | Path | None = None,
    task_runner: Any | None = None,
) -> AgentStateService:
    return AgentStateService(
        state_dir=state_dir,
        llm=llm,
        soul=soul,
        medium_dir=medium_dir,
        task_runner=task_runner,
    )
