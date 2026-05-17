"""base/dag_orchestrator.py — DagOrchestrator：ManifestPlanSpec 上的完整 DAG 编排器。

完整 DAG 链路
-------------
bootstrap → DagGraphManager → _execute 并发主循环
              │
              ├─ AtomicPlanner.assess()
              │     ├─ flat    → expand_flat：同层注册子图，递归调度
              │     ├─ nested  → expand_nested：子 DagOrchestrator.run()
              │     └─ atomic  → dispatch_atomic：RunnableNode.run()
              │
              └─ BaseReplanner（on_task_failed / on_plan_complete）

设计约束
--------
· 无 try/except：节点执行异常直接向上传播，调用方决定处理方式。
· AtomicPlanner 通过构造注入；NodeRegistry 用于构建 ManifestExecutor / NodeVerifier。
· DagGraphManager 是唯一运行时状态源；ManifestPlanSpec 是唯一声明式源。
· Replanner 对 spec 调用 apply_patch() 后，_sync_graph_to_spec 自动同步图结构。
"""
from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from .budget import DecompositionBudget, TopologyKind, is_atomic
from .components.atomic_planner import AtomicPlanner
from .components.node_spec import NodeManifest
from .components.runtime import NodeResult, RunnableNode
from .orchestration import (
    BaseReplanner,
    DagGraphManager,
    ManifestAwarePlanSpec,
    OrchestratorEvent,
    OrchestratorResult,
    ReplanDecision,
)
from .plan_spec import ManifestPatch, ManifestPlanSpec
from .registry import NodeRegistry, get_registry
from .types import NodeStatus


class DagOrchestrator:
    """驱动「初始规划 → 原子展开 → 并发执行 → 重规划」完整闭环。

    使用方式
    --------
    1. 有 Planner（返回 ManifestPlanSpec）::

           orch = DagOrchestrator(planner=my_planner, atomic_planner=ap)
           result = asyncio.run(orch.run("研究最新量子计算进展"))

    2. 无 Planner，单节点 bootstrap（AtomicPlanner 递归长出完整图）::

           orch = DagOrchestrator(atomic_planner=ap)
           result = asyncio.run(orch.run("研究最新量子计算进展"))

    参数
    ----
    planner         实现 BasePlanSpec plan(goal) 的规划器；None 则用单节点 bootstrap。
    atomic_planner  原子粒度决策器（inject or build via register_defaults）。
    registry        节点执行器/校验器工厂；None 时取全局单例 get_registry()。
    replanner       重规划器；None 则跳过所有重规划触发器。
    budget          递归展开预算；默认 DecompositionBudget()（depth=3, width=8）。
    parallel_limit  同时执行节点数上限；0 表示不限制（受 NodeRuntimeManager 线程池约束）。
    replanner_triggers
                    触发 Replanner 的事件集合；默认 {"on_task_failed","on_plan_complete"}。
    """

    def __init__(
        self,
        planner: Any | None = None,
        *,
        atomic_planner: AtomicPlanner | None = None,
        registry: NodeRegistry | None = None,
        replanner: BaseReplanner | None = None,
        budget: DecompositionBudget | None = None,
        parallel_limit: int = 0,
        replanner_triggers: set[str] | None = None,
        _executor_pool: ThreadPoolExecutor | None = None,
    ) -> None:
        self._planner = planner
        self._atomic_planner = atomic_planner
        self._registry = registry
        self._replanner = replanner
        self._budget = budget or DecompositionBudget()
        self._parallel_limit = parallel_limit
        self._replanner_triggers = replanner_triggers or {
            "on_task_failed",
            "on_plan_complete",
        }
        self._executor_pool = _executor_pool
        self._event_callbacks: list[Callable[[OrchestratorEvent], None]] = []
        self._outputs: dict[str, Any] = {}
        self._current_graph: DagGraphManager | None = None
        self._replan_cycle: int = 0

    # ── 公开 API ────────────────────────────────────────────────────────────────

    async def run(self, goal: str) -> OrchestratorResult:
        """为 goal 执行完整的规划 + 执行 + 重规划闭环，返回编排结果。"""
        plan_id = str(uuid.uuid4())
        self._outputs = {}
        self._replan_cycle = 0

        spec = await self._bootstrap(goal, plan_id)
        graph = DagGraphManager.from_spec(spec)
        self._current_graph = graph

        self._emit(OrchestratorEvent(
            plan_id=plan_id, kind="plan.start",
            payload={"title": spec.title, "node_count": len(spec.all_node_ids())},
        ))

        await self._execute(spec, graph, plan_id, self._budget)

        if self._replanner is not None and "on_plan_complete" in self._replanner_triggers:
            decision = await self._call_replanner(spec, graph, plan_id, "on_plan_complete")
            if decision.decision in ("done", "abort"):
                status = "done" if decision.decision == "done" else "aborted"
                self._emit(OrchestratorEvent(
                    plan_id=plan_id, kind="plan.complete", payload={"status": status},
                ))
                return OrchestratorResult(
                    plan_id=plan_id,
                    status=status,
                    answer=decision.conclusion,
                    spec=spec,
                    graph=graph,
                )

        self._emit(OrchestratorEvent(
            plan_id=plan_id, kind="plan.complete", payload={"status": "done"},
        ))
        return OrchestratorResult(plan_id=plan_id, status="done", spec=spec, graph=graph)

    def subscribe(self, callback: Callable[[OrchestratorEvent], None]) -> None:
        self._event_callbacks.append(callback)

    def progress(self) -> tuple[int, int]:
        if self._current_graph is None:
            return (0, 0)
        return self._current_graph.progress()

    # ── Bootstrap ───────────────────────────────────────────────────────────────

    async def _bootstrap(self, goal: str, plan_id: str) -> ManifestAwarePlanSpec:
        if self._planner is None:
            spec: ManifestAwarePlanSpec = ManifestPlanSpec.single_node(goal)
        else:
            raw = await self._planner.plan(goal)
            if not isinstance(raw, ManifestAwarePlanSpec):
                raise TypeError(
                    f"planner.plan() must return a ManifestAwarePlanSpec "
                    f"(implement manifest(node_id) + apply_patch()), "
                    f"got {type(raw).__name__}"
                )
            spec = raw
        spec.plan_id = plan_id  # type: ignore[misc]  # protocol declares getter only
        return spec

    # ── 执行主循环 ──────────────────────────────────────────────────────────────

    async def _execute(
        self,
        spec: ManifestAwarePlanSpec,
        graph: DagGraphManager,
        plan_id: str,
        budget: DecompositionBudget,
    ) -> None:
        """所有 pending 节点同时启动，各自等待依赖完成后再执行（event-driven）。"""
        semaphore: asyncio.Semaphore | None = (
            asyncio.Semaphore(self._parallel_limit) if self._parallel_limit > 0 else None
        )
        done_events: dict[str, asyncio.Event] = {
            nid: asyncio.Event() for nid in graph.all_node_ids()
        }

        async def run_when_ready(node_id: str) -> None:
            # 等待所有直接依赖完成
            dep_waits = [
                done_events[d].wait()
                for d in graph.node_deps(node_id)
                if d in done_events
            ]
            if dep_waits:
                await asyncio.gather(*dep_waits)

            # 等待期间节点可能已被 Replanner 从图中移除，直接退出
            if not graph.has_node(node_id):
                return

            # 可能在等待期间被 Replanner 标记为 skipped
            if graph.node_status(node_id) == NodeStatus.skipped:
                done_events[node_id].set()
                self._emit(OrchestratorEvent(
                    plan_id=plan_id, kind="task.skipped",
                    payload={"task_id": node_id},
                ))
                return

            graph.set_node_status(node_id, NodeStatus.running)
            self._emit(OrchestratorEvent(
                plan_id=plan_id, kind="task.start",
                payload={"task_id": node_id},
            ))

            # ── 原子规划层（AtomicPlanner 决策） ──────────────────────────────
            if self._atomic_planner is not None and not budget.exhausted:
                manifest = spec.manifest(node_id)
                if not is_atomic(manifest, budget):
                    decision = await self._atomic_planner.assess(manifest, budget)

                    if decision.kind == TopologyKind.flat and decision.sub_manifests:
                        await self._expand_flat(
                            node_id, decision.sub_manifests, decision.output_node_id,
                            spec, graph, done_events, plan_id, budget, run_when_ready,
                        )
                        return

                    if decision.kind == TopologyKind.nested and decision.sub_manifests:
                        output = await self._expand_nested(
                            node_id, spec.manifest(node_id),
                            decision.sub_manifests, decision.output_node_id,
                            plan_id, budget,
                        )
                        self._outputs[node_id] = output
                        graph.set_node_status(node_id, NodeStatus.done, result=output)
                        done_events[node_id].set()
                        self._emit(OrchestratorEvent(
                            plan_id=plan_id, kind="task.complete",
                            payload={"task_id": node_id, "kind": "nested"},
                        ))
                        return
                    # kind == atomic：跌落到原子执行

            # ── 原子执行 ──────────────────────────────────────────────────────
            if semaphore is not None:
                async with semaphore:
                    result = await self._dispatch_atomic(node_id, spec)
            else:
                result = await self._dispatch_atomic(node_id, spec)

            await self._handle_node_result(
                node_id, result, spec, graph, done_events, plan_id, run_when_ready
            )

        # 所有 pending 节点同时启动
        pending = [
            nid for nid in graph.all_node_ids()
            if graph.node_status(nid) == NodeStatus.pending
        ]
        await asyncio.gather(*[run_when_ready(nid) for nid in pending])

    # ── Flat 展开 ───────────────────────────────────────────────────────────────

    async def _expand_flat(
        self,
        parent_id: str,
        sub_manifests: tuple[NodeManifest, ...],
        output_node_id: str,
        spec: ManifestAwarePlanSpec,
        graph: DagGraphManager,
        done_events: dict[str, asyncio.Event],
        plan_id: str,
        budget: DecompositionBudget,
        run_when_ready: Callable,
    ) -> None:
        """将 sub_manifests 注册为同层兄弟节点，递归调度并将出口结果接回父节点。"""
        spec.apply_patch(ManifestPatch(add_manifests=sub_manifests))
        for m in sub_manifests:
            graph.add_node(m.task_id, frozenset(m.depends_on))
            done_events[m.task_id] = asyncio.Event()

        self._emit(OrchestratorEvent(
            plan_id=plan_id, kind="task.flat_expand",
            payload={"task_id": parent_id, "sub_count": len(sub_manifests)},
        ))
        await asyncio.gather(*[run_when_ready(m.task_id) for m in sub_manifests])

        exit_id = output_node_id or sub_manifests[-1].task_id
        output = self._outputs.get(exit_id, "")
        self._outputs[parent_id] = output
        graph.set_node_status(parent_id, NodeStatus.done, result=output)
        done_events[parent_id].set()
        self._emit(OrchestratorEvent(
            plan_id=plan_id, kind="task.complete",
            payload={"task_id": parent_id, "kind": "flat"},
        ))

    # ── Nested 展开 ─────────────────────────────────────────────────────────────

    async def _expand_nested(
        self,
        parent_id: str,
        parent_manifest: NodeManifest,
        sub_manifests: tuple[NodeManifest, ...],
        output_node_id: str,
        plan_id: str,
        budget: DecompositionBudget,
    ) -> Any:
        """为 sub_manifests 启动子 DagOrchestrator，返回出口节点的输出值。"""
        child_spec = ManifestPlanSpec(
            title=f"sub:{parent_id}",
            objective=parent_manifest.description,
            manifests=list(sub_manifests),
            plan_id=f"{plan_id}.{parent_id}",
        )
        child_graph = DagGraphManager.from_spec(child_spec)

        child = DagOrchestrator(
            atomic_planner=self._atomic_planner,
            registry=self._registry,
            replanner=self._replanner,
            budget=budget.descend(),
            parallel_limit=self._parallel_limit,
            replanner_triggers=self._replanner_triggers,
            _executor_pool=self._executor_pool,
        )
        for cb in self._event_callbacks:
            child.subscribe(cb)

        self._emit(OrchestratorEvent(
            plan_id=plan_id, kind="task.nested_run",
            payload={"task_id": parent_id, "sub_count": len(sub_manifests)},
        ))
        await child._execute(child_spec, child_graph, plan_id, budget.descend())

        exit_id = output_node_id or (sub_manifests[-1].task_id if sub_manifests else "")
        return child._outputs.get(exit_id, "")

    # ── 原子节点执行 ────────────────────────────────────────────────────────────

    async def _dispatch_atomic(
        self,
        node_id: str,
        spec: ManifestAwarePlanSpec,
    ) -> NodeResult:
        """通过 RunnableNode 在线程池中同步执行节点，返回 NodeResult。"""
        manifest = spec.manifest(node_id)
        reg = self._registry or get_registry()
        executor = reg.build_executor(manifest.tool_package)
        verifier = reg.build_verifier()

        inputs: dict[str, Any] = {
            dep: self._outputs[dep]
            for dep in manifest.depends_on
            if dep in self._outputs
        }

        node = RunnableNode(manifest, executor, verifier)
        loop = asyncio.get_running_loop()
        result: NodeResult = await loop.run_in_executor(
            self._executor_pool, node.run, inputs
        )
        self._outputs[node_id] = result.output
        return result

    # ── 节点结果处理（含 Replanner 触发） ──────────────────────────────────────

    async def _handle_node_result(
        self,
        node_id: str,
        result: NodeResult,
        spec: ManifestAwarePlanSpec,
        graph: DagGraphManager,
        done_events: dict[str, asyncio.Event],
        plan_id: str,
        run_when_ready: Callable,
    ) -> None:
        if result.status == NodeStatus.done:
            graph.set_node_status(node_id, NodeStatus.done, result=result.output)
            done_events[node_id].set()
            self._emit(OrchestratorEvent(
                plan_id=plan_id, kind="task.complete",
                payload={"task_id": node_id},
            ))
        else:
            graph.set_node_status(node_id, NodeStatus.failed, error=result.error)
            done_events[node_id].set()
            failed_payload: dict[str, Any] = {"task_id": node_id, "error": result.error}
            if result.verification is not None:
                failed_payload["verification_status"] = result.verification.status.value
                failed_payload["verification_verdict"] = result.verification.verdict
                failed_payload["verification_report"] = result.verification.report
            self._emit(OrchestratorEvent(
                plan_id=plan_id, kind="task.failed",
                payload=failed_payload,
            ))

            if self._replanner is None or "on_task_failed" not in self._replanner_triggers:
                return

            self._replan_cycle += 1
            decision = await self._call_replanner(
                spec, graph, plan_id, "on_task_failed", self._replan_cycle
            )
            if decision.decision == "modify":
                if decision.patch is None:
                    raise ValueError(
                        f"ReplanDecision.decision == 'modify' but patch is None "
                        f"(trigger=on_task_failed, cycle={self._replan_cycle}); "
                        f"Replanner must set patch when requesting plan modification."
                    )
                spec.apply_patch(decision.patch)
                new_ids = self._sync_graph_to_spec(spec, graph, done_events)
                if new_ids:
                    await asyncio.gather(*[run_when_ready(nid) for nid in new_ids])

    # ── Replanner ───────────────────────────────────────────────────────────────

    async def _call_replanner(
        self,
        spec: ManifestAwarePlanSpec,
        graph: DagGraphManager,
        plan_id: str,
        trigger: str,
        cycle: int = 0,
    ) -> ReplanDecision:
        assert self._replanner is not None
        self._emit(OrchestratorEvent(
            plan_id=plan_id, kind="replan.start",
            payload={"trigger": trigger, "cycle": cycle},
        ))
        decision = await self._replanner.replan(spec, graph, trigger=trigger, cycle=cycle)
        self._emit(OrchestratorEvent(
            plan_id=plan_id, kind="replan.complete",
            payload={"decision": decision.decision, "reason": decision.reason},
        ))
        return decision

    # ── 图与 Spec 同步 ──────────────────────────────────────────────────────────

    def _sync_graph_to_spec(
        self,
        spec: ManifestAwarePlanSpec,
        graph: DagGraphManager,
        done_events: dict[str, asyncio.Event],
    ) -> list[str]:
        """将 spec.apply_patch 后的结构变更同步到 DagGraphManager。

        返回新添加的 node_id 列表（需要由调用方启动 run_when_ready）。
        """
        graph_ids = set(graph.all_node_ids())
        spec_ids = set(spec.all_node_ids())

        for rid in graph_ids - spec_ids:
            graph.remove_node(rid)
            done_events.pop(rid, None)

        added: list[str] = []
        for aid in spec_ids - graph_ids:
            graph.add_node(aid, spec.node_deps(aid))
            done_events[aid] = asyncio.Event()
            added.append(aid)

        return added

    # ── 事件发射 ────────────────────────────────────────────────────────────────

    def _emit(self, event: OrchestratorEvent) -> None:
        for cb in self._event_callbacks:
            cb(event)
