"""document/orchestrator.py — 将文档 IR 接到 base.DagOrchestrator。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from agent.flow.base.components.atomic_planner import AtomicPlanner
from agent.flow.base.dag_orchestrator import DagOrchestrator
from agent.flow.base.orchestration import BaseReplanner, OrchestratorEvent, OrchestratorResult
from agent.flow.base.registry import NodeRegistry
from agent.flow.base.budget import DecompositionBudget

from .files import load_dag_plan_document
from .manifest import dag_document_to_manifest_spec
from .markdown import DagMarkdownIO
from .model import DagPlanDocument
from .planner import DagDocumentPlanner, MarkdownDocumentPlanner, StaticManifestPlanner
from .validate import assert_valid_dag_document


class DocumentDagOrchestrator:
    """文档入口 + base.DagOrchestrator：统一原子展开、注册表执行与重规划。"""

    def __init__(
        self,
        *,
        atomic_planner: AtomicPlanner | None = None,
        registry: NodeRegistry | None = None,
        replanner: BaseReplanner | None = None,
        budget: DecompositionBudget | None = None,
        parallel_limit: int = 0,
        replanner_triggers: set[str] | None = None,
        _executor_pool: ThreadPoolExecutor | None = None,
    ) -> None:
        self._atomic_planner = atomic_planner
        self._registry = registry
        self._replanner = replanner
        self._budget = budget
        self._parallel_limit = parallel_limit
        self._replanner_triggers = replanner_triggers
        self._executor_pool = _executor_pool
        self._inner: DagOrchestrator | None = None
        self._event_callbacks: list[Callable[[OrchestratorEvent], None]] = []

    def subscribe(self, callback: Callable[[OrchestratorEvent], None]) -> None:
        self._event_callbacks.append(callback)

    def progress(self) -> tuple[int, int]:
        if self._inner is None:
            return (0, 0)
        return self._inner.progress()

    def _make(self, planner: Any) -> DagOrchestrator:
        orch = DagOrchestrator(
            planner=planner,
            atomic_planner=self._atomic_planner,
            registry=self._registry,
            replanner=self._replanner,
            budget=self._budget,
            parallel_limit=self._parallel_limit,
            replanner_triggers=self._replanner_triggers,
            _executor_pool=self._executor_pool,
        )
        for cb in self._event_callbacks:
            orch.subscribe(cb)
        self._inner = orch
        return orch

    async def run_document(
        self,
        doc: DagPlanDocument,
        *,
        goal: str | None = None,
    ) -> OrchestratorResult:
        assert_valid_dag_document(doc)
        spec = dag_document_to_manifest_spec(doc)
        planner = StaticManifestPlanner(spec)
        g = goal or doc.objective or doc.title
        return await self._make(planner).run(g)

    async def run_builder_planner(self, planner: DagDocumentPlanner, *, goal: str) -> OrchestratorResult:
        return await self._make(planner).run(goal)

    async def run_markdown(self, markdown: str) -> OrchestratorResult:
        planner = MarkdownDocumentPlanner()
        return await self._make(planner).run(markdown)

    async def run_path(
        self,
        path: str | Path,
        *,
        goal: str | None = None,
        strict: bool = True,
    ) -> OrchestratorResult:
        doc = load_dag_plan_document(path, strict=strict)
        return await self.run_document(doc, goal=goal)

    def parse_markdown(self, markdown: str) -> DagPlanDocument:
        return DagMarkdownIO.from_markdown(markdown, strict=True)

    def parse_path(self, path: str | Path, *, strict: bool = True) -> DagPlanDocument:
        return load_dag_plan_document(path, strict=strict)
