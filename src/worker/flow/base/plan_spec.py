"""base/plan_spec.py — ManifestPlanSpec：BasePlanSpec 的具体实现。

以 NodeManifest 列表作为计划内容。支持：
  · 通过 ManifestPatch.apply_patch() 动态增/删/改节点声明。
  · ManifestPlanSpec.single_node(goal) 作为最简 bootstrap：单节点种子图，
    全靠 AtomicPlanner 递归展开，无需初始化 Planner。
"""
from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass, field
from typing import Any

from .components.node_spec import NodeManifest


@dataclass
class ManifestPatch:
    """ManifestPlanSpec.apply_patch() 的补丁载荷。

    add_manifests         添加（或覆盖同 task_id 的已有）节点声明。
    remove_ids            按 task_id 删除节点。
    update_descriptions   按 task_id 覆写 description 字段。
    add_deps              按 task_id 追加 depends_on 条目（不覆盖原有依赖）。
    """

    add_manifests: tuple[NodeManifest, ...] = ()
    remove_ids: tuple[str, ...] = ()
    update_descriptions: dict[str, str] = field(default_factory=dict)
    add_deps: dict[str, tuple[str, ...]] = field(default_factory=dict)


class ManifestPlanSpec:
    """BasePlanSpec 的具体实现，以 NodeManifest 字典持有计划内容。

    plan_id 在创建时生成（或由调用方赋值），之后只读；
    title / objective 描述本计划的目标，供 Replanner 阅读。
    """

    def __init__(
        self,
        title: str,
        objective: str,
        manifests: list[NodeManifest],
        plan_id: str = "",
    ) -> None:
        self._plan_id = plan_id or str(uuid.uuid4())
        self._title = title
        self._objective = objective
        self._manifests: dict[str, NodeManifest] = {m.task_id: m for m in manifests}

    @classmethod
    def single_node(cls, goal: str, task_id: str = "root") -> "ManifestPlanSpec":
        """最简 bootstrap：单节点种子图，全靠 AtomicPlanner 递归展开。

        适用于无初始化 Planner 时，从一个描述目标的根节点出发，
        AtomicPlanner 在首次调度该节点时将其展开为完整子图。
        """
        root = NodeManifest(task_id=task_id, description=goal)
        return cls(title=goal[:80], objective=goal, manifests=[root])

    # ── BasePlanSpec 接口 ──────────────────────────────────────────────────────

    @property
    def plan_id(self) -> str:
        return self._plan_id

    @plan_id.setter
    def plan_id(self, value: str) -> None:
        self._plan_id = value

    @property
    def title(self) -> str:
        return self._title

    @property
    def objective(self) -> str:
        return self._objective

    def all_node_ids(self) -> list[str]:
        return list(self._manifests)

    def node_deps(self, node_id: str) -> frozenset[str]:
        return frozenset(self._manifests[node_id].depends_on)

    def node_description(self, node_id: str) -> str:
        return self._manifests[node_id].description

    def apply_patch(self, patch: Any) -> None:
        """应用 ManifestPatch；非 ManifestPatch 类型立即抛出 TypeError。"""
        if not isinstance(patch, ManifestPatch):
            raise TypeError(
                f"ManifestPlanSpec.apply_patch expects ManifestPatch, "
                f"got {type(patch).__name__}. "
                f"Replanner 必须在 ReplanDecision.patch 中放置 ManifestPatch 实例。"
            )
        for rid in patch.remove_ids:
            self._manifests.pop(rid, None)
        for m in patch.add_manifests:
            self._manifests[m.task_id] = m
        for tid, new_desc in patch.update_descriptions.items():
            if tid in self._manifests:
                self._manifests[tid] = dataclasses.replace(
                    self._manifests[tid], description=new_desc
                )
        for tid, extra_deps in patch.add_deps.items():
            if tid in self._manifests:
                old = self._manifests[tid]
                self._manifests[tid] = dataclasses.replace(
                    old, depends_on=old.depends_on + extra_deps
                )

    # ── ManifestPlanSpec 专有 ──────────────────────────────────────────────────

    def manifest(self, node_id: str) -> NodeManifest:
        """直接取 NodeManifest；AtomicPlanner 与 Executor 调用此方法。"""
        return self._manifests[node_id]

    def all_manifests(self) -> list[NodeManifest]:
        return list(self._manifests.values())
