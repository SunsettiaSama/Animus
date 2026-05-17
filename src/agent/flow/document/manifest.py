"""document/manifest.py — DagPlanDocument ↔ base.ManifestPlanSpec / NodeManifest。"""
from __future__ import annotations

from agent.flow.base.components.node_spec import NodeManifest
from agent.flow.base.plan_spec import ManifestPlanSpec

from .model import DagDocNode, DagPlanDocument


def dag_document_to_manifest_spec(doc: DagPlanDocument) -> ManifestPlanSpec:
    """将文档 IR 编译为 ManifestPlanSpec（base 声明式计划）。"""
    manifests = [_node_to_manifest(n) for n in doc.nodes]
    return ManifestPlanSpec(
        title=doc.title,
        objective=doc.objective,
        manifests=manifests,
        plan_id=doc.plan_id,
    )


def manifest_spec_to_dag_document(spec: ManifestPlanSpec) -> DagPlanDocument:
    """从 ManifestPlanSpec 还原文档视图（丢失的 Markdown 排版信息不恢复）。"""
    nodes: list[DagDocNode] = []
    for m in spec.all_manifests():
        nodes.append(
            DagDocNode(
                task_id=m.task_id,
                description=m.description,
                depends_on=m.depends_on,
                tool_package=m.tool_package,
                max_steps=m.max_steps,
                system_note=m.system_note,
                tags=dict(m.tags),
            )
        )
    return DagPlanDocument(
        title=spec.title,
        objective=spec.objective,
        nodes=nodes,
        plan_id=spec.plan_id,
    )


def _node_to_manifest(n: DagDocNode) -> NodeManifest:
    return NodeManifest(
        task_id=n.task_id,
        description=n.description,
        depends_on=n.depends_on,
        tool_package=n.tool_package,
        max_steps=n.max_steps,
        system_note=n.system_note,
        tags=dict(n.tags),
    )
