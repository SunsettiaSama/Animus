"""document/model.py — 面向 DAG 的轻量文档 IR（声明式），与 base 层 Manifest 对齐。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class DagDocNode:
    """DAG 中的一个节点，对应 base.NodeManifest 的文档视图。"""

    task_id: str
    description: str
    depends_on: tuple[str, ...] = ()
    tool_package: str | None = None
    max_steps: int | None = None
    system_note: str = ""
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class DagPlanDocument:
    """文档形态的 DAG 计划：扁平节点列表 + 元信息。

    调度与补丁语义由 agent.flow.base.ManifestPlanSpec / DagOrchestrator 承载；
    本类型仅负责人工可读载体与双向转换。
    """

    title: str
    objective: str
    nodes: list[DagDocNode]
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def node_ids(self) -> frozenset[str]:
        return frozenset(n.task_id for n in self.nodes)
