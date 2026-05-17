"""document/planner.py — BasePlanner 的具体实现：静态文档 / Markdown。"""
from __future__ import annotations

from typing import Any, Callable

from agent.flow.base.orchestration import BasePlanSpec
from agent.flow.base.plan_spec import ManifestPlanSpec

from .manifest import dag_document_to_manifest_spec
from .markdown import DagMarkdownIO
from .model import DagPlanDocument
from .validate import assert_valid_dag_document


class StaticManifestPlanner:
    """返回预先编译好的 ManifestPlanSpec（base.BasePlanner 协议实现）。"""

    def __init__(self, spec: ManifestPlanSpec) -> None:
        self._spec = spec

    async def plan(
        self,
        goal: str,
        *,
        context: dict[str, Any] | None = None,
        step_callback: Callable[[int, str, str, str], None] | None = None,
    ) -> BasePlanSpec:
        _ = (goal, context, step_callback)
        return self._spec


class DagDocumentPlanner:
    """由 DagPlanDocument 构建 ManifestPlanSpec。"""

    def __init__(self, doc: DagPlanDocument) -> None:
        assert_valid_dag_document(doc)
        self._spec = dag_document_to_manifest_spec(doc)

    async def plan(
        self,
        goal: str,
        *,
        context: dict[str, Any] | None = None,
        step_callback: Callable[[int, str, str, str], None] | None = None,
    ) -> BasePlanSpec:
        _ = (goal, context, step_callback)
        return self._spec


class MarkdownDocumentPlanner:
    """goal 参数传入完整 Markdown 正文，解析为 ManifestPlanSpec。"""

    async def plan(
        self,
        goal: str,
        *,
        context: dict[str, Any] | None = None,
        step_callback: Callable[[int, str, str, str], None] | None = None,
    ) -> BasePlanSpec:
        _ = (context, step_callback)
        doc = DagMarkdownIO.from_markdown(goal, strict=True)
        assert_valid_dag_document(doc)
        return dag_document_to_manifest_spec(doc)
