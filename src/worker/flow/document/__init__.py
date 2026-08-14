"""基于文档的 DAG 开发层：声明式文档 IR → base.ManifestPlanSpec → DagOrchestrator。

支持后缀：``.md`` / ``.markdown``、``.docx``（``python-docx``）。
与 cluster 的互操作见 cluster_bridge 模块。
"""
from __future__ import annotations

from .builder import DagPlanBuilder
from .files import load_dag_plan_document, save_dag_plan_document, supported_plan_suffixes
from .manifest import dag_document_to_manifest_spec, manifest_spec_to_dag_document
from .markdown import DagMarkdownIO, DagMarkdownParseError
from .model import DagDocNode, DagPlanDocument
from .orchestrator import DocumentDagOrchestrator
from .planner import DagDocumentPlanner, MarkdownDocumentPlanner, StaticManifestPlanner
from .validate import assert_valid_dag_document, validate_dag_document
from .word_docx import DagWordIO

__all__ = [
    "DagDocNode",
    "DagPlanDocument",
    "DagPlanBuilder",
    "DagMarkdownIO",
    "DagMarkdownParseError",
    "DagWordIO",
    "load_dag_plan_document",
    "save_dag_plan_document",
    "supported_plan_suffixes",
    "dag_document_to_manifest_spec",
    "manifest_spec_to_dag_document",
    "validate_dag_document",
    "assert_valid_dag_document",
    "StaticManifestPlanner",
    "DagDocumentPlanner",
    "MarkdownDocumentPlanner",
    "DocumentDagOrchestrator",
]
