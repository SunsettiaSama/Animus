"""dag_runner.py — DagOrchestrator benchmark runner。

100 个场景覆盖：
  · simple  (30)  — 单链、并行分叉、合并汇聚、树形拓扑，无 AtomicPlanner / Replanner
  · medium  (40)  — AtomicPlanner 平铺展开、嵌套展开、多级依赖、混合拓扑
  · complex (30)  — 节点失败 + 重规划、预算耗尽、大图综合

运行方式（在 src/ 目录下）：
    python -m test.benchmark run --gate regression
    python -m pytest src/test/benchmark/test_dag_bench.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

_SRC = Path(__file__).resolve().parent.parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from agent.flow.base.budget import DecompositionBudget, TopologyKind
from agent.flow.base.components.node_spec import NodeManifest, TopologyDecision
from agent.flow.base.dag_orchestrator import DagOrchestrator
from agent.flow.base.orchestration import OrchestratorEvent, OrchestratorResult, ReplanDecision
from agent.flow.base.plan_spec import ManifestPatch, ManifestPlanSpec
from agent.flow.base.registry import NodeRegistry
from test.benchmark.dag_mock import (
    MockAtomicPlanner,
    MockManifestExecutor,
    MockNodeVerifier,
    ScriptedReplanner,
    StaticManifestPlanner,
)
from test.benchmark.metrics import MetricsCollector, ScenarioResult

if TYPE_CHECKING:
    pass


# ── DagScenario ───────────────────────────────────────────────────────────────


@dataclass
class DagScenario:
    """单个 DAG benchmark 场景的完整描述。"""

    name: str
    category: str           # simple | medium | complex
    description: str
    goal: str

    # 初始计划节点
    manifests: list[NodeManifest]

    # executor 输出脚本: task_id → 返回值
    outputs: dict[str, str] = field(default_factory=dict)

    # 强制失败的节点 task_id 集合（MockNodeVerifier 用）
    failing_nodes: set[str] = field(default_factory=set)

    # AtomicPlanner 脚本: task_id → TopologyDecision
    # None = 不启用 AtomicPlanner
    atomic_decisions: dict[str, TopologyDecision] | None = None

    # Replanner 脚本: trigger → ReplanDecision
    # None = 不启用 Replanner
    replan_decisions: dict[str, ReplanDecision] | None = None

    # Replanner 触发事件集合（None 时从 replan_decisions 键推导）
    replanner_triggers: set[str] | None = None

    # 展开预算
    budget: DecompositionBudget | None = None

    # 预期结果
    expected_status: str = "done"
    expected_node_count: int = -1       # -1 = 不校验
    expected_flat_expands: int = 0
    expected_nested_expands: int = 0
    expected_replan_cycles: int = 0
    expected_failed_nodes: int = 0
    expected_min_done: int = -1         # 最少 done 节点数，-1 = 不校验

    max_wall_ms: float = 15000.0


# ── Event collector ───────────────────────────────────────────────────────────


@dataclass
class _DagMetrics:
    flat_expands: int = 0
    nested_expands: int = 0
    replan_cycles: int = 0
    failed_nodes: int = 0
    done_nodes: int = 0
    skipped_nodes: int = 0
    plan_status: str = "unknown"

    def on_event(self, event: OrchestratorEvent) -> None:
        k = event.kind
        if k == "task.flat_expand":
            self.flat_expands += 1
        elif k == "task.nested_run":
            self.nested_expands += 1
        elif k == "replan.start":
            self.replan_cycles += 1
        elif k == "task.failed":
            self.failed_nodes += 1
        elif k == "task.complete":
            self.done_nodes += 1
        elif k == "task.skipped":
            self.skipped_nodes += 1
        elif k == "plan.complete":
            self.plan_status = event.payload.get("status", "done")


# ── Single scenario runner ────────────────────────────────────────────────────


def _run_one(scenario: DagScenario) -> ScenarioResult:
    collector = MetricsCollector(scenario.name)
    dag_metrics = _DagMetrics()

    # ── Build ManifestPlanSpec ────────────────────────────────────────────────
    spec = ManifestPlanSpec(
        title=scenario.name,
        objective=scenario.goal,
        manifests=scenario.manifests,
    )

    # ── Build mock registry ───────────────────────────────────────────────────
    executor = MockManifestExecutor(output_map=scenario.outputs)
    verifier = MockNodeVerifier(failing_ids=scenario.failing_nodes) if scenario.failing_nodes else None

    registry = NodeRegistry()
    registry.set_executor_factory(lambda _pkg: executor)
    if verifier is not None:
        registry.set_verifier_factory(lambda: verifier)

    # ── Build AtomicPlanner ───────────────────────────────────────────────────
    atomic_planner: MockAtomicPlanner | None = None
    if scenario.atomic_decisions is not None:
        atomic_planner = MockAtomicPlanner(decisions=scenario.atomic_decisions)

    # ── Build Replanner ───────────────────────────────────────────────────────
    replanner: ScriptedReplanner | None = None
    triggers: set[str] | None = None
    if scenario.replan_decisions is not None:
        replanner = ScriptedReplanner(
            decisions=scenario.replan_decisions,
            triggers=scenario.replanner_triggers,
        )
        triggers = scenario.replanner_triggers or set(scenario.replan_decisions)

    # ── Build Orchestrator ────────────────────────────────────────────────────
    planner = StaticManifestPlanner(spec)
    budget = scenario.budget or DecompositionBudget()

    orch = DagOrchestrator(
        planner=planner,
        atomic_planner=atomic_planner,
        registry=registry,
        replanner=replanner,
        budget=budget,
        replanner_triggers=triggers,
    )
    orch.subscribe(dag_metrics.on_event)

    # ── Run ───────────────────────────────────────────────────────────────────
    t0 = time.perf_counter()
    result: OrchestratorResult | None = None
    run_error: str | None = None

    try:
        result = asyncio.run(orch.run(scenario.goal))
    except Exception as exc:
        run_error = str(exc)

    wall_ms = (time.perf_counter() - t0) * 1000

    # ── Evaluate ──────────────────────────────────────────────────────────────
    quality = _compute_quality(scenario, dag_metrics, result, wall_ms)
    status = "done" if run_error is None and (result and result.status in ("done", "aborted")) else "failed"
    if status == "done":
        collector.mark_done(result.answer if result else "")
    else:
        collector.mark_failed("execution_error", run_error)

    sr = collector.finalize(quality_score=quality)

    # inject DAG-specific info into trace
    sr = ScenarioResult(
        scenario=sr.scenario,
        status=status,
        failure_cause=sr.failure_cause,
        wall_ms=wall_ms,
        steps=dag_metrics.done_nodes + dag_metrics.failed_nodes + dag_metrics.skipped_nodes,
        llm_retries=0,
        llm_calls=[],
        tool_calls=[],
        quality_score=quality,
        total_prompt_tokens=0,
        total_completion_tokens=0,
        error=run_error,
        trace={
            "flat_expands":   dag_metrics.flat_expands,
            "nested_expands": dag_metrics.nested_expands,
            "replan_cycles":  dag_metrics.replan_cycles,
            "failed_nodes":   dag_metrics.failed_nodes,
            "done_nodes":     dag_metrics.done_nodes,
            "skipped_nodes":  dag_metrics.skipped_nodes,
            "plan_status":    dag_metrics.plan_status,
            "category":       scenario.category,
        },
    )
    return sr


def _compute_quality(
    scenario: DagScenario,
    dag: _DagMetrics,
    result: OrchestratorResult | None,
    wall_ms: float,
) -> float:
    checks: list[bool] = []

    if scenario.expected_status != "any":
        got = "done" if result and result.status in ("done", "aborted") else "failed"
        checks.append(got == scenario.expected_status)

    if scenario.expected_flat_expands >= 0:
        checks.append(dag.flat_expands == scenario.expected_flat_expands)

    if scenario.expected_nested_expands >= 0:
        checks.append(dag.nested_expands == scenario.expected_nested_expands)

    if scenario.expected_replan_cycles >= 0:
        checks.append(dag.replan_cycles == scenario.expected_replan_cycles)

    if scenario.expected_failed_nodes >= 0:
        checks.append(dag.failed_nodes == scenario.expected_failed_nodes)

    if scenario.expected_min_done >= 0:
        checks.append(dag.done_nodes >= scenario.expected_min_done)

    if wall_ms > scenario.max_wall_ms:
        checks.append(False)

    if not checks:
        return 1.0
    return sum(checks) / len(checks)


# ── Scenario factory helpers ──────────────────────────────────────────────────


def _m(*args, **kwargs) -> NodeManifest:
    """短名称包装 NodeManifest 构造。"""
    return NodeManifest(*args, **kwargs)


def _td_atomic(reason: str = "mock atomic") -> TopologyDecision:
    return TopologyDecision(kind=TopologyKind.atomic, reason=reason)


def _td_flat(
    sub_ids: list[str],
    sub_descs: list[str],
    sub_deps: list[tuple[str, ...]] | None = None,
    output_node_id: str = "",
) -> TopologyDecision:
    sub_deps = sub_deps or [() for _ in sub_ids]
    subs = tuple(
        _m(task_id=tid, description=desc, depends_on=dep)
        for tid, desc, dep in zip(sub_ids, sub_descs, sub_deps)
    )
    return TopologyDecision(
        kind=TopologyKind.flat,
        reason="mock flat expand",
        sub_manifests=subs,
        output_node_id=output_node_id or (sub_ids[-1] if sub_ids else ""),
    )


def _td_nested(
    sub_ids: list[str],
    sub_descs: list[str],
    sub_deps: list[tuple[str, ...]] | None = None,
    output_node_id: str = "",
) -> TopologyDecision:
    sub_deps = sub_deps or [() for _ in sub_ids]
    subs = tuple(
        _m(task_id=tid, description=desc, depends_on=dep)
        for tid, desc, dep in zip(sub_ids, sub_descs, sub_deps)
    )
    return TopologyDecision(
        kind=TopologyKind.nested,
        reason="mock nested expand",
        sub_manifests=subs,
        output_node_id=output_node_id or (sub_ids[-1] if sub_ids else ""),
    )


def _replan_add(
    add_ids: list[str],
    add_descs: list[str],
    add_deps: list[tuple[str, ...]] | None = None,
    remove_ids: tuple[str, ...] = (),
    conclusion: str = "",
) -> ReplanDecision:
    add_deps = add_deps or [() for _ in add_ids]
    patch = ManifestPatch(
        add_manifests=tuple(
            _m(task_id=tid, description=desc, depends_on=dep)
            for tid, desc, dep in zip(add_ids, add_descs, add_deps)
        ),
        remove_ids=remove_ids,
    )
    return ReplanDecision(decision="modify", reason="replan: add recovery", patch=patch, conclusion=conclusion)


def _replan_done(conclusion: str = "plan complete") -> ReplanDecision:
    return ReplanDecision(decision="done", conclusion=conclusion)


def _replan_abort(conclusion: str = "abort") -> ReplanDecision:
    return ReplanDecision(decision="abort", conclusion=conclusion)


# ── 100 SCENARIOS ─────────────────────────────────────────────────────────────
#
# SIMPLE  (s01–s30)  — 无 AtomicPlanner / Replanner，测试基础 DAG 调度
# MEDIUM  (m01–m40)  — 有 AtomicPlanner，测试展开逻辑
# COMPLEX (c01–c30)  — 有 Replanner / budget 限制，测试重规划与深度控制
# ─────────────────────────────────────────────────────────────────────────────


def _build_simple_scenarios() -> list[DagScenario]:
    s: list[DagScenario] = []

    # ── 单节点 (s01-s05) ──────────────────────────────────────────────────────
    for i, pkg in enumerate(["compute", "fetch", "transform", "analyze", "store"], 1):
        s.append(DagScenario(
            name=f"s{i:02d}_single_{pkg}",
            category="simple",
            description=f"单节点任务，工具包 {pkg}",
            goal=f"Execute single {pkg} task",
            manifests=[_m(f"node_a", f"Use {pkg} to process data")],
            outputs={"node_a": f"output_{pkg}"},
            expected_status="done",
            expected_min_done=1,
        ))

    # ── 两节点链 (s06-s10) ───────────────────────────────────────────────────
    for i, (a_desc, b_desc) in enumerate([
        ("fetch data", "process data"),
        ("parse input", "validate output"),
        ("gather info", "summarize info"),
        ("read file", "write result"),
        ("call api", "handle response"),
    ], 6):
        s.append(DagScenario(
            name=f"s{i:02d}_chain_2",
            category="simple",
            description=f"两节点串行链: {a_desc} → {b_desc}",
            goal="Execute 2-node chain",
            manifests=[
                _m("A", a_desc),
                _m("B", b_desc, depends_on=("A",)),
            ],
            outputs={"A": "data_a", "B": "data_b"},
            expected_min_done=2,
        ))

    # ── 三节点链 (s11-s15) ───────────────────────────────────────────────────
    for i in range(11, 16):
        s.append(DagScenario(
            name=f"s{i:02d}_chain_3",
            category="simple",
            description="三节点串行链 A→B→C",
            goal="Execute 3-node chain",
            manifests=[
                _m("A", "step one"),
                _m("B", "step two", depends_on=("A",)),
                _m("C", "step three", depends_on=("B",)),
            ],
            outputs={"A": "r_a", "B": "r_b", "C": "r_c"},
            expected_min_done=3,
        ))

    # ── 五节点链 (s16-s17) ───────────────────────────────────────────────────
    for i in range(16, 18):
        s.append(DagScenario(
            name=f"s{i:02d}_chain_5",
            category="simple",
            description="五节点串行链",
            goal="Execute 5-node chain",
            manifests=[
                _m("N1", "stage 1"),
                _m("N2", "stage 2", depends_on=("N1",)),
                _m("N3", "stage 3", depends_on=("N2",)),
                _m("N4", "stage 4", depends_on=("N3",)),
                _m("N5", "stage 5", depends_on=("N4",)),
            ],
            expected_min_done=5,
        ))

    # ── 并行节点 (s18-s22) ───────────────────────────────────────────────────
    for i, n_par in enumerate([2, 3, 4, 5, 8], 18):
        manifests = [_m(f"P{j}", f"parallel task {j}") for j in range(1, n_par + 1)]
        s.append(DagScenario(
            name=f"s{i:02d}_parallel_{n_par}",
            category="simple",
            description=f"{n_par} 个完全并行节点",
            goal=f"Execute {n_par} parallel tasks",
            manifests=manifests,
            expected_min_done=n_par,
        ))

    # ── 菱形 fork-join (s23-s25) ─────────────────────────────────────────────
    for i, n_branches in enumerate([2, 3, 4], 23):
        branches = [_m(f"B{j}", f"branch {j}", depends_on=("root",)) for j in range(1, n_branches + 1)]
        join_deps = tuple(f"B{j}" for j in range(1, n_branches + 1))
        s.append(DagScenario(
            name=f"s{i:02d}_diamond_{n_branches}",
            category="simple",
            description=f"菱形: 1 根 → {n_branches} 分支 → 1 汇聚",
            goal="Execute diamond DAG",
            manifests=[
                _m("root", "root task"),
                *branches,
                _m("join", "join task", depends_on=join_deps),
            ],
            expected_min_done=n_branches + 2,
        ))

    # ── 树形结构 (s26-s27) ───────────────────────────────────────────────────
    s.append(DagScenario(
        name="s26_tree_2level",
        category="simple",
        description="两层树: root → [L1a, L1b] → [L2a, L2b, L2c, L2d]",
        goal="Execute 2-level tree",
        manifests=[
            _m("root", "root"),
            _m("L1a", "left branch", depends_on=("root",)),
            _m("L1b", "right branch", depends_on=("root",)),
            _m("L2a", "leaf a", depends_on=("L1a",)),
            _m("L2b", "leaf b", depends_on=("L1a",)),
            _m("L2c", "leaf c", depends_on=("L1b",)),
            _m("L2d", "leaf d", depends_on=("L1b",)),
        ],
        expected_min_done=7,
    ))

    s.append(DagScenario(
        name="s27_star",
        category="simple",
        description="星形: 中心节点 → 5 叶节点",
        goal="Execute star topology",
        manifests=[
            _m("hub", "central hub"),
            *[_m(f"spoke_{j}", f"spoke {j}", depends_on=("hub",)) for j in range(1, 6)],
        ],
        expected_min_done=6,
    ))

    # ── 双菱形 (s28) ─────────────────────────────────────────────────────────
    s.append(DagScenario(
        name="s28_double_diamond",
        category="simple",
        description="双菱形: A→[B,C]→D→[E,F]→G",
        goal="Execute double diamond",
        manifests=[
            _m("A", "start"),
            _m("B", "fork B", depends_on=("A",)),
            _m("C", "fork C", depends_on=("A",)),
            _m("D", "join mid", depends_on=("B", "C")),
            _m("E", "fork E", depends_on=("D",)),
            _m("F", "fork F", depends_on=("D",)),
            _m("G", "final join", depends_on=("E", "F")),
        ],
        expected_min_done=7,
    ))

    # ── 扇形 fan-in-out (s29) ────────────────────────────────────────────────
    s.append(DagScenario(
        name="s29_fan_in_out",
        category="simple",
        description="扇入扇出: [A1,A2,A3]→B→[C1,C2,C3]",
        goal="Execute fan-in-out",
        manifests=[
            _m("A1", "input 1"),
            _m("A2", "input 2"),
            _m("A3", "input 3"),
            _m("B", "process", depends_on=("A1", "A2", "A3")),
            _m("C1", "output 1", depends_on=("B",)),
            _m("C2", "output 2", depends_on=("B",)),
            _m("C3", "output 3", depends_on=("B",)),
        ],
        expected_min_done=7,
    ))

    # ── 十节点链 (s30) ───────────────────────────────────────────────────────
    chain = [_m("S1", "step 1")]
    for j in range(2, 11):
        chain.append(_m(f"S{j}", f"step {j}", depends_on=(f"S{j-1}",)))
    s.append(DagScenario(
        name="s30_chain_10",
        category="simple",
        description="十节点串行链",
        goal="Execute 10-node chain",
        manifests=chain,
        expected_min_done=10,
    ))

    return s


def _build_medium_scenarios() -> list[DagScenario]:
    s: list[DagScenario] = []

    # ── 平铺展开 (m01-m10) ────────────────────────────────────────────────────
    # m01: 单节点展开为 2
    s.append(DagScenario(
        name="m01_flat_expand_1x2",
        category="medium",
        description="单节点 A 平铺展开为 A1, A2",
        goal="Flat expand single node to 2",
        manifests=[_m("A", "complex task")],
        atomic_decisions={"A": _td_flat(["A1", "A2"], ["sub-task 1", "sub-task 2"])},
        expected_flat_expands=1,
        expected_min_done=2,
    ))

    # m02: 单节点展开为 3
    s.append(DagScenario(
        name="m02_flat_expand_1x3",
        category="medium",
        description="单节点 A 平铺展开为 A1, A2, A3",
        goal="Flat expand to 3 sub-nodes",
        manifests=[_m("A", "triple task")],
        atomic_decisions={"A": _td_flat(["A1", "A2", "A3"], ["s1", "s2", "s3"])},
        expected_flat_expands=1,
        expected_min_done=3,
    ))

    # m03: 单节点展开为 4
    s.append(DagScenario(
        name="m03_flat_expand_1x4",
        category="medium",
        description="单节点 A 平铺展开为 4 个子节点",
        goal="Flat expand to 4",
        manifests=[_m("A", "quad task")],
        atomic_decisions={"A": _td_flat(
            ["A1", "A2", "A3", "A4"],
            ["s1", "s2", "s3", "s4"],
        )},
        expected_flat_expands=1,
        expected_min_done=4,
    ))

    # m04: 两个节点都展开
    s.append(DagScenario(
        name="m04_flat_expand_2_nodes",
        category="medium",
        description="A 和 B 都展开为各自的子节点集",
        goal="Two nodes both flat expand",
        manifests=[
            _m("A", "task A complex"),
            _m("B", "task B complex"),
        ],
        atomic_decisions={
            "A": _td_flat(["A1", "A2"], ["A sub1", "A sub2"]),
            "B": _td_flat(["B1", "B2"], ["B sub1", "B sub2"]),
        },
        expected_flat_expands=2,
        expected_min_done=4,
    ))

    # m05: 链中间节点展开（展开后子节点有依赖）
    s.append(DagScenario(
        name="m05_flat_expand_chained_subs",
        category="medium",
        description="链中节点 B 展开为带依赖的子节点",
        goal="Flat expand with chained sub-nodes",
        manifests=[
            _m("A", "prepare"),
            _m("B", "expand me", depends_on=("A",)),
            _m("C", "finalize", depends_on=("B",)),
        ],
        atomic_decisions={
            "B": _td_flat(
                ["B1", "B2"],
                ["B first", "B second"],
                sub_deps=[(), ("B1",)],
                output_node_id="B2",
            )
        },
        expected_flat_expands=1,
        expected_min_done=4,  # A, B1, B2, C
    ))

    # m06: 并行节点中仅一个展开
    s.append(DagScenario(
        name="m06_flat_expand_one_of_parallel",
        category="medium",
        description="并行节点 [A, B] 中仅 A 展开",
        goal="One of parallel nodes expands",
        manifests=[
            _m("A", "expandable A"),
            _m("B", "simple B"),
        ],
        atomic_decisions={"A": _td_flat(["A1", "A2"], ["A sub1", "A sub2"])},
        expected_flat_expands=1,
        expected_min_done=3,  # A1, A2, B
    ))

    # m07: 展开后再展开（展开的子节点也会被展开）
    s.append(DagScenario(
        name="m07_flat_expand_cascade",
        category="medium",
        description="A 展开后 A1 再次展开",
        goal="Cascading flat expansion",
        manifests=[_m("A", "cascade root")],
        atomic_decisions={
            "A":  _td_flat(["A1", "A2"], ["expand again", "leaf"]),
            "A1": _td_flat(["A1a", "A1b"], ["deep leaf 1", "deep leaf 2"]),
        },
        expected_flat_expands=2,
        expected_min_done=3,  # A1a, A1b, A2
    ))

    # m08: 展开后输出节点有后继依赖
    s.append(DagScenario(
        name="m08_flat_expand_with_output_node",
        category="medium",
        description="A 展开，指定 output_node_id=A2，后继 B 等待 A（即 A2）",
        goal="Flat expand output_node_id test",
        manifests=[
            _m("A", "to expand"),
            _m("B", "waits for A", depends_on=("A",)),
        ],
        atomic_decisions={"A": _td_flat(
            ["A1", "A2"],
            ["prep", "final sub"],
            sub_deps=[(), ("A1",)],
            output_node_id="A2",
        )},
        expected_flat_expands=1,
        expected_min_done=3,
    ))

    # m09: 展开在链起点
    s.append(DagScenario(
        name="m09_flat_expand_start_node",
        category="medium",
        description="链的起始节点展开",
        goal="Start node flat expansion",
        manifests=[
            _m("Start", "starting task"),
            _m("Mid", "middle", depends_on=("Start",)),
            _m("End", "ending", depends_on=("Mid",)),
        ],
        atomic_decisions={"Start": _td_flat(["S1", "S2"], ["init 1", "init 2"])},
        expected_flat_expands=1,
        expected_min_done=4,  # S1, S2, Mid, End
    ))

    # m10: 展开在链末尾
    s.append(DagScenario(
        name="m10_flat_expand_end_node",
        category="medium",
        description="链的末尾节点展开",
        goal="End node flat expansion",
        manifests=[
            _m("A", "first"),
            _m("B", "second", depends_on=("A",)),
            _m("C", "final to expand", depends_on=("B",)),
        ],
        atomic_decisions={"C": _td_flat(["C1", "C2"], ["final 1", "final 2"])},
        expected_flat_expands=1,
        expected_min_done=4,  # A, B, C1, C2
    ))

    # ── 嵌套展开 (m11-m20) ───────────────────────────────────────────────────

    # m11: 单节点嵌套展开为 2 子节点
    s.append(DagScenario(
        name="m11_nested_expand_basic",
        category="medium",
        description="节点 A 嵌套展开为 sub-orchestrator",
        goal="Basic nested expansion",
        manifests=[_m("A", "nested work")],
        atomic_decisions={"A": _td_nested(["N1", "N2"], ["nested 1", "nested 2"])},
        expected_nested_expands=1,
        expected_min_done=0,  # nested 节点以 A 的输出返回，A done 算 1
    ))

    # m12: 链中间节点嵌套展开
    s.append(DagScenario(
        name="m12_nested_expand_in_chain",
        category="medium",
        description="链 A→B→C，B 嵌套展开",
        goal="Nested expand in chain",
        manifests=[
            _m("A", "prepare"),
            _m("B", "nested task", depends_on=("A",)),
            _m("C", "finalize", depends_on=("B",)),
        ],
        atomic_decisions={"B": _td_nested(
            ["N1", "N2", "N3"],
            ["step 1", "step 2", "step 3"],
            sub_deps=[(), ("N1",), ("N2",)],
            output_node_id="N3",
        )},
        expected_nested_expands=1,
        expected_min_done=2,  # A, B (nested), C
    ))

    # m13: 多节点嵌套展开
    s.append(DagScenario(
        name="m13_nested_expand_two_nodes",
        category="medium",
        description="A 和 B 均嵌套展开（互相独立）",
        goal="Two nested expansions",
        manifests=[
            _m("A", "nested A"),
            _m("B", "nested B"),
        ],
        atomic_decisions={
            "A": _td_nested(["A_n1", "A_n2"], ["A sub 1", "A sub 2"]),
            "B": _td_nested(["B_n1", "B_n2"], ["B sub 1", "B sub 2"]),
        },
        expected_nested_expands=2,
    ))

    # m14: 嵌套展开后有后继
    s.append(DagScenario(
        name="m14_nested_expand_with_successor",
        category="medium",
        description="A 嵌套展开，后继 B 等待 A 完成",
        goal="Nested expand with downstream",
        manifests=[
            _m("A", "big task"),
            _m("B", "post process", depends_on=("A",)),
        ],
        atomic_decisions={"A": _td_nested(
            ["a1", "a2", "a3"],
            ["init", "process", "output"],
            sub_deps=[(), ("a1",), ("a2",)],
            output_node_id="a3",
        )},
        expected_nested_expands=1,
        expected_min_done=1,  # A (nested), B
    ))

    # m15: 嵌套展开（子图内并行）
    s.append(DagScenario(
        name="m15_nested_expand_parallel_subs",
        category="medium",
        description="A 嵌套展开，子图内 [n1,n2] 并行后 n3 汇聚",
        goal="Nested with parallel sub-graph",
        manifests=[_m("A", "parallel nested")],
        atomic_decisions={"A": _td_nested(
            ["n1", "n2", "n3"],
            ["parallel 1", "parallel 2", "join"],
            sub_deps=[(), (), ("n1", "n2")],
            output_node_id="n3",
        )},
        expected_nested_expands=1,
    ))

    # m16-m20: 多级依赖 + 混合拓扑
    # m16: 3 级深 chain
    s.append(DagScenario(
        name="m16_deep_3_levels",
        category="medium",
        description="3 级深度: L1→L2→L3，每层 2 个节点",
        goal="Deep 3-level graph",
        manifests=[
            _m("L1a", "level 1 a"), _m("L1b", "level 1 b"),
            _m("L2a", "level 2 a", depends_on=("L1a", "L1b")),
            _m("L2b", "level 2 b", depends_on=("L1a",)),
            _m("L3", "level 3", depends_on=("L2a", "L2b")),
        ],
        atomic_decisions={},  # 启用 AtomicPlanner 但全 atomic
        expected_flat_expands=0,
        expected_min_done=5,
    ))

    # m17: 4 级深 graph
    s.append(DagScenario(
        name="m17_deep_4_levels",
        category="medium",
        description="4 级图: 每级扇出一个新分支",
        goal="Deep 4-level graph",
        manifests=[
            _m("A", "root"),
            _m("B", "l2", depends_on=("A",)),
            _m("C", "l2b", depends_on=("A",)),
            _m("D", "l3", depends_on=("B",)),
            _m("E", "l3b", depends_on=("B", "C")),
            _m("F", "l4", depends_on=("D", "E")),
        ],
        atomic_decisions={},
        expected_min_done=6,
    ))

    # m18: 平铺 + 常规混合
    s.append(DagScenario(
        name="m18_mixed_flat_and_normal",
        category="medium",
        description="部分节点平铺展开，部分正常执行",
        goal="Mixed flat and normal nodes",
        manifests=[
            _m("A", "expand A"),
            _m("B", "normal B"),
            _m("C", "expand C", depends_on=("A", "B")),
        ],
        atomic_decisions={
            "A": _td_flat(["A1", "A2"], ["A sub 1", "A sub 2"]),
            "C": _td_flat(["C1", "C2", "C3"], ["C s1", "C s2", "C s3"]),
        },
        expected_flat_expands=2,
        expected_min_done=6,  # A1,A2, B, C1,C2,C3
    ))

    # m19: 嵌套 + 平铺混合
    s.append(DagScenario(
        name="m19_mixed_nested_and_flat",
        category="medium",
        description="A 嵌套展开，B 平铺展开，C 汇聚",
        goal="Mixed nested and flat expansion",
        manifests=[
            _m("A", "nested task"),
            _m("B", "flat task"),
            _m("C", "join", depends_on=("A", "B")),
        ],
        atomic_decisions={
            "A": _td_nested(["An1", "An2"], ["nested 1", "nested 2"]),
            "B": _td_flat(["Bf1", "Bf2"], ["flat 1", "flat 2"]),
        },
        expected_flat_expands=1,
        expected_nested_expands=1,
        expected_min_done=3,  # A(nested), Bf1, Bf2, C
    ))

    # m20: 预算 depth=2 的展开
    s.append(DagScenario(
        name="m20_budget_depth2",
        category="medium",
        description="使用 depth=2 预算，允许两层嵌套展开",
        goal="Nested expand within depth=2 budget",
        manifests=[_m("root", "expandable root")],
        atomic_decisions={
            "root": _td_nested(
                ["r1", "r2"],
                ["expand r1", "leaf r2"],
                sub_deps=[(), ("r1",)],
            ),
            "r1": _td_flat(["r1a", "r1b"], ["deep 1a", "deep 1b"]),
        },
        budget=DecompositionBudget(max_depth=2),
        expected_nested_expands=1,
        expected_flat_expands=1,
    ))

    # m21-m30: 更多混合 + 多级场景
    for i, width in enumerate([3, 4, 5, 6, 7], 21):
        manifests = (
            [_m("root", f"wide root {width}")]
            + [_m(f"W{j}", f"worker {j}", depends_on=("root",)) for j in range(1, width + 1)]
            + [_m("agg", "aggregate", depends_on=tuple(f"W{j}" for j in range(1, width + 1)))]
        )
        s.append(DagScenario(
            name=f"m{i:02d}_wide_{width}_with_planner",
            category="medium",
            description=f"宽度 {width} 的扇出汇聚，所有节点经 AtomicPlanner 判断为 atomic",
            goal=f"Wide graph {width} with AtomicPlanner",
            manifests=manifests,
            atomic_decisions={},  # 全部返回 atomic
            expected_flat_expands=0,
            expected_nested_expands=0,
            expected_min_done=width + 2,
        ))

    for i, n_chain in enumerate([4, 5, 6, 7, 8], 26):
        chain = [_m("C1", "first")]
        for j in range(2, n_chain + 1):
            chain.append(_m(f"C{j}", f"chain step {j}", depends_on=(f"C{j-1}",)))
        s.append(DagScenario(
            name=f"m{i:02d}_chain_{n_chain}_with_planner",
            category="medium",
            description=f"{n_chain} 节点链，AtomicPlanner 判断全部 atomic",
            goal=f"{n_chain}-node chain with AtomicPlanner",
            manifests=chain,
            atomic_decisions={},
            expected_min_done=n_chain,
        ))

    # m31-m40: 复杂展开场景
    # m31: 嵌套+嵌套（两个独立节点）
    s.append(DagScenario(
        name="m31_nested_chain_in_subgraph",
        category="medium",
        description="A 嵌套展开为 3 节点链，B 串行依赖 A",
        goal="Nested chain subgraph",
        manifests=[
            _m("A", "big A"),
            _m("B", "post B", depends_on=("A",)),
        ],
        atomic_decisions={"A": _td_nested(
            ["a1", "a2", "a3"],
            ["init", "compute", "store"],
            sub_deps=[(), ("a1",), ("a2",)],
            output_node_id="a3",
        )},
        expected_nested_expands=1,
        expected_min_done=1,
    ))

    s.append(DagScenario(
        name="m32_flat_diamond",
        category="medium",
        description="菱形中 root 展开，分支汇聚到 join",
        goal="Flat expand diamond root",
        manifests=[
            _m("root", "expandable root"),
            _m("br1", "branch 1", depends_on=("root",)),
            _m("br2", "branch 2", depends_on=("root",)),
            _m("join", "join", depends_on=("br1", "br2")),
        ],
        atomic_decisions={"root": _td_flat(["r1", "r2"], ["root sub 1", "root sub 2"])},
        expected_flat_expands=1,
        expected_min_done=5,  # r1,r2, br1,br2, join
    ))

    for i in range(33, 41):
        # 渐变宽度的平铺展开：i-32 个原始节点，每个展开为 2 个子节点
        n = i - 30
        orig = [_m(f"X{j}", f"orig {j}") for j in range(1, n + 1)]
        decisions = {f"X{j}": _td_flat([f"X{j}a", f"X{j}b"], [f"sub {j}a", f"sub {j}b"]) for j in range(1, n + 1)}
        s.append(DagScenario(
            name=f"m{i:02d}_all_flat_{n}x2",
            category="medium",
            description=f"{n} 个节点全部平铺展开为 2 个子节点",
            goal=f"All {n} nodes flat expand x2",
            manifests=orig,
            atomic_decisions=decisions,
            expected_flat_expands=n,
            expected_min_done=n * 2,
        ))

    return s


def _build_complex_scenarios() -> list[DagScenario]:
    s: list[DagScenario] = []

    # ── 节点失败 + replan 修复 (c01-c10) ─────────────────────────────────────
    for i in range(1, 11):
        fail_id = f"fail_node_{i}"
        recover_id = f"recover_{i}"
        s.append(DagScenario(
            name=f"c{i:02d}_replan_recover",
            category="complex",
            description=f"节点 {fail_id} 失败后 Replanner 添加恢复节点",
            goal=f"Fail and recover scenario {i}",
            manifests=[
                _m("pre", "prepare step"),
                _m(fail_id, "this will fail", depends_on=("pre",)),
                _m("post", "post step", depends_on=(fail_id,)),
            ],
            failing_nodes={fail_id},
            replan_decisions={
                "on_task_failed": _replan_add(
                    [recover_id, "post"],
                    ["recovery task", "post step (retry)"],
                    add_deps=[("pre",), (recover_id,)],
                    remove_ids=(fail_id, "post"),
                ),
            },
            replanner_triggers={"on_task_failed"},
            expected_failed_nodes=1,
            expected_replan_cycles=1,
            expected_status="done",
        ))

    # ── 节点失败 → replan abort (c11-c15) ────────────────────────────────────
    for i in range(11, 16):
        fail_id = f"critical_{i}"
        s.append(DagScenario(
            name=f"c{i:02d}_replan_abort",
            category="complex",
            description=f"关键节点 {fail_id} 失败，Replanner 中止计划",
            goal=f"Critical failure abort {i}",
            manifests=[
                _m("setup", "setup"),
                _m(fail_id, "critical step", depends_on=("setup",)),
                _m("cleanup", "cleanup", depends_on=(fail_id,)),
            ],
            failing_nodes={fail_id},
            replan_decisions={
                "on_task_failed": _replan_abort(f"critical step {i} failed, aborting"),
            },
            replanner_triggers={"on_task_failed"},
            expected_failed_nodes=1,
            expected_replan_cycles=1,
            expected_status="done",  # abort 也算 done（OrchestratorResult.status="aborted"）
        ))

    # ── plan_complete 触发 → Replanner 宣告完成 (c16-c20) ───────────────────
    for i in range(16, 21):
        s.append(DagScenario(
            name=f"c{i:02d}_replan_done_on_complete",
            category="complex",
            description="所有节点完成后 Replanner 给出结论",
            goal=f"Plan complete with replanner conclusion {i}",
            manifests=[
                _m("A", "task A"),
                _m("B", "task B", depends_on=("A",)),
            ],
            replan_decisions={
                "on_plan_complete": _replan_done(f"All done, conclusion {i}"),
            },
            replanner_triggers={"on_plan_complete"},
            expected_replan_cycles=1,
            expected_status="done",
            expected_min_done=2,
        ))

    # ── budget 耗尽强制 atomic (c21-c25) ─────────────────────────────────────
    for i in range(21, 26):
        s.append(DagScenario(
            name=f"c{i:02d}_budget_exhausted",
            category="complex",
            description="budget depth=0，AtomicPlanner 强制返回 atomic（budget.exhausted）",
            goal=f"Budget exhausted forces atomic {i}",
            manifests=[_m(f"node_{i}", "would expand but budget=0")],
            atomic_decisions={
                f"node_{i}": _td_flat([f"sub1_{i}", f"sub2_{i}"], ["sub 1", "sub 2"])
            },
            budget=DecompositionBudget(max_depth=0),  # 预算耗尽
            expected_flat_expands=0,  # 不会展开，budget 已耗尽
            expected_min_done=1,      # node 直接 atomic 执行
        ))

    # ── 大图综合测试 (c26-c30) ────────────────────────────────────────────────
    # c26: 12 节点图，部分展开，1 个失败+修复
    s.append(DagScenario(
        name="c26_large_graph_with_replan",
        category="complex",
        description="12 节点图，B 展开，C 失败后 Replanner 添加修复节点",
        goal="Large graph with expansion and replan",
        manifests=[
            _m("A", "init"),
            _m("B", "expand B", depends_on=("A",)),
            _m("C", "will fail", depends_on=("A",)),
            _m("D", "waits B C", depends_on=("B", "C")),
            _m("E", "parallel A", depends_on=("A",)),
            _m("F", "final", depends_on=("D", "E")),
        ],
        failing_nodes={"C"},
        atomic_decisions={"B": _td_flat(["B1", "B2", "B3"], ["b1", "b2", "b3"])},
        replan_decisions={
            "on_task_failed": _replan_add(
                ["C_fix", "D"],
                ["fix C", "waits B_end C_fix"],
                add_deps=[("A",), ("B3", "C_fix")],
                remove_ids=("C", "D"),
            ),
        },
        replanner_triggers={"on_task_failed"},
        expected_flat_expands=1,
        expected_replan_cycles=1,
        expected_failed_nodes=1,
    ))

    # c27: 15 节点图，纯 AtomicPlanner 判断全部 atomic
    nodes_c27 = (
        [_m("root", "root")]
        + [_m(f"L{j}", f"l1 node {j}", depends_on=("root",)) for j in range(1, 6)]
        + [_m(f"M{j}", f"l2 node {j}", depends_on=(f"L{((j-1)%5)+1}",)) for j in range(1, 6)]
        + [_m(f"T{j}", f"l3 node {j}", depends_on=(f"M{j}",)) for j in range(1, 4)]
        + [_m("fin", "final", depends_on=("T1", "T2", "T3"))]
    )
    s.append(DagScenario(
        name="c27_large_15_nodes_atomic",
        category="complex",
        description="15 节点图，AtomicPlanner 全部返回 atomic",
        goal="Large 15-node all-atomic",
        manifests=nodes_c27,
        atomic_decisions={},
        expected_flat_expands=0,
        expected_min_done=15,
    ))

    # c28: 并行 + 多次失败，Replanner 只修复第一次
    s.append(DagScenario(
        name="c28_parallel_fail_replan",
        category="complex",
        description="并行执行中 F1 失败，Replanner 修复后 F2 正常执行",
        goal="Parallel fail with partial replan",
        manifests=[
            _m("F1", "fail me"),
            _m("F2", "fine"),
            _m("end", "end", depends_on=("F1", "F2")),
        ],
        failing_nodes={"F1"},
        replan_decisions={
            "on_task_failed": _replan_add(
                ["F1_fix", "end"],
                ["fix for F1", "end rebuilt"],
                add_deps=[(), ("F1_fix", "F2")],
                remove_ids=("F1", "end"),
            ),
        },
        replanner_triggers={"on_task_failed"},
        expected_failed_nodes=1,
        expected_replan_cycles=1,
    ))

    # c29: 嵌套展开 + 失败
    s.append(DagScenario(
        name="c29_nested_with_failure",
        category="complex",
        description="A 嵌套展开，展开后的父节点 A done，后继 B 正常执行",
        goal="Nested expand then success",
        manifests=[
            _m("A", "nested A"),
            _m("B", "depends A", depends_on=("A",)),
        ],
        atomic_decisions={"A": _td_nested(
            ["a1", "a2"],
            ["nested a1", "nested a2"],
            sub_deps=[(), ("a1",)],
            output_node_id="a2",
        )},
        expected_nested_expands=1,
        expected_failed_nodes=0,
        expected_min_done=1,
    ))

    # c30: 综合最大场景（展开 + 并行 + 重规划 + budget depth=2）
    s.append(DagScenario(
        name="c30_comprehensive",
        category="complex",
        description="综合场景: 展开 + 并行 + 重规划，budget depth=2",
        goal="Comprehensive DAG test",
        manifests=[
            _m("root", "start"),
            _m("expand_me", "will expand", depends_on=("root",)),
            _m("parallel", "runs in parallel", depends_on=("root",)),
            _m("fail_here", "will fail", depends_on=("expand_me",)),
            _m("join", "final", depends_on=("parallel",)),
        ],
        failing_nodes={"fail_here"},
        atomic_decisions={"expand_me": _td_flat(
            ["em1", "em2"],
            ["expand sub 1", "expand sub 2"],
            sub_deps=[(), ("em1",)],
            output_node_id="em2",
        )},
        replan_decisions={
            "on_task_failed": _replan_add(
                ["recovery", "join"],
                ["recovery step", "final rebuilt"],
                add_deps=[("em2",), ("recovery", "parallel")],
                remove_ids=("fail_here", "join"),
            ),
        },
        replanner_triggers={"on_task_failed"},
        budget=DecompositionBudget(max_depth=2),
        expected_flat_expands=1,
        expected_replan_cycles=1,
        expected_failed_nodes=1,
    ))

    return s


def build_all_scenarios() -> list[DagScenario]:
    return _build_simple_scenarios() + _build_medium_scenarios() + _build_complex_scenarios()


# ── DagOrchestratorRunner ─────────────────────────────────────────────────────


class DagOrchestratorRunner:
    """regression gate runner: 100 DAG 场景全覆盖。"""

    name = "dag_orchestrator"
    gate = "regression"

    def __init__(
        self,
        scenarios: list[DagScenario] | None = None,
        category_filter: str | None = None,  # "simple" | "medium" | "complex" | None
    ) -> None:
        all_sc = scenarios or build_all_scenarios()
        if category_filter:
            all_sc = [sc for sc in all_sc if sc.category == category_filter]
        self._scenarios = all_sc

    def run_all(self) -> list[ScenarioResult]:
        results: list[ScenarioResult] = []
        for sc in self._scenarios:
            results.append(_run_one(sc))
        return results

    def describe(self) -> str:
        cats: dict[str, int] = {}
        for sc in self._scenarios:
            cats[sc.category] = cats.get(sc.category, 0) + 1
        summary = ", ".join(f"{v} {k}" for k, v in sorted(cats.items()))
        return (
            f"{len(self._scenarios)} DAG scenarios "
            f"({summary}) via DagOrchestrator + MockManifestExecutor"
        )
