"""document/builder.py — 代码侧拼装 DagPlanDocument（开发期 DSL）。"""
from __future__ import annotations

from collections.abc import Sequence

from .model import DagDocNode, DagPlanDocument


class DagPlanBuilder:
    """链式构造 DAG 文档，最终交给 manifest.Document ↔ DagOrchestrator。"""

    def __init__(self, title: str, objective: str, *, plan_id: str = "") -> None:
        self._title = title
        self._objective = objective
        self._plan_id = plan_id
        self._nodes: list[DagDocNode] = []

    def task(
        self,
        task_id: str,
        description: str,
        *,
        depends_on: Sequence[str] | None = None,
        tool_package: str | None = None,
        max_steps: int | None = None,
        system_note: str = "",
        tags: dict[str, str] | None = None,
    ) -> DagPlanBuilder:
        deps = tuple(depends_on) if depends_on else ()
        self._nodes.append(
            DagDocNode(
                task_id=task_id,
                description=description,
                depends_on=deps,
                tool_package=tool_package,
                max_steps=max_steps,
                system_note=system_note,
                tags=dict(tags or {}),
            )
        )
        return self

    def build(self) -> DagPlanDocument:
        doc = DagPlanDocument(
            title=self._title,
            objective=self._objective,
            nodes=list(self._nodes),
        )
        if self._plan_id:
            doc.plan_id = self._plan_id
        return doc
