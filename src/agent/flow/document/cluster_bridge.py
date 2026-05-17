"""document/cluster_bridge.py — 与 cluster.PlanDocument 互转（可选依赖）。"""
from __future__ import annotations

from agent.flow.cluster.document import PlanDocument, PlanModule, PlanTask

from .model import DagDocNode, DagPlanDocument


def dag_document_from_cluster_plan(plan: PlanDocument) -> DagPlanDocument:
    """将模块化 PlanDocument 拍平为 DagPlanDocument。"""
    nodes: list[DagDocNode] = []
    for m in plan.modules:
        for t in m.tasks:
            tool = t.params.get("tool_package")
            if tool is None and t.profile not in ("minimal", ""):
                tool = t.profile
            tags = {"module": m.name}
            nodes.append(
                DagDocNode(
                    task_id=t.task_id,
                    description=t.description,
                    depends_on=tuple(t.depends_on),
                    tool_package=tool,
                    max_steps=t.max_steps,
                    system_note=str(t.params.get("system_note", "") or ""),
                    tags=tags,
                )
            )
    return DagPlanDocument(
        title=plan.title,
        objective=plan.objective,
        nodes=nodes,
        plan_id=plan.plan_id,
    )


def cluster_plan_from_dag_document(doc: DagPlanDocument) -> PlanDocument:
    """将扁平 DagPlanDocument 写回单模块 PlanDocument（模块名 document）。"""
    tasks: list[PlanTask] = []
    for n in doc.nodes:
        params: dict[str, object] = {}
        if n.system_note:
            params["system_note"] = n.system_note
        if n.tool_package:
            params["tool_package"] = n.tool_package
        mod_name = n.tags.get("module", "document")
        profile = n.tool_package or "minimal"
        tasks.append(
            PlanTask(
                task_id=n.task_id,
                description=n.description,
                module=mod_name,
                profile=profile,
                depends_on=list(n.depends_on),
                max_steps=n.max_steps,
                params=params,
            )
        )
    module = PlanModule(name="document", tasks=tasks)
    return PlanDocument(
        plan_id=doc.plan_id,
        title=doc.title,
        objective=doc.objective,
        modules=[module],
    )
