"""base/orchestration.py — 多 DAG 集群编排协议层。

四个核心抽象
-----------
BaseGraphManager    图与图节点管理器
                    · 管理 DAG 的运行时状态：节点 ID、依赖关系、生命周期状态。
                    · 提供 ready_nodes() 调度接口、add_node / remove_node 动态变更、
                      pause / resume Human-in-the-Loop 支持。
                    · DagGraphManager 是开箱即用的标准实现，基于 base/graph.py 算法。

BasePlanSpec        计划说明书
                    · 声明式描述「要做什么」：目标、节点描述、依赖关系。
                    · 由 Planner 产出，Replanner 和 NodeExecutor 只读；
                      Replanner 通过 ReplanDecision.patches 向外声明修改意图，
                      由 Orchestrator 调用 apply_patch() 落地。
                    · 不持有运行时状态（状态由 BaseGraphManager 管理）。

BasePlanner         规划器
                    · 接收自然语言目标 → 返回 BasePlanSpec。
                    · plan() 为 async，step_callback 用于流式推送 TAO 推理步骤。

BaseReplanner       重规划器
                    · 接收 (BasePlanSpec, BaseGraphManager, trigger) → 返回 ReplanDecision。
                    · should_trigger() 声明关心的事件集合。
                    · ReplanDecision 为基类（decision / conclusion / reason），
                      具体集群通过继承添加补丁指令（patches / confidence 等）。

其余辅助类型
-----------
ReplanDecision      重规划决策基类（可被子类扩展）。
BaseNodeExecutor    执行单个节点（取 node_id + spec，不修改 graph 状态）。
OrchestratorEvent   生命周期事件基类（点分层级 kind 字符串）。
OrchestratorResult  编排最终结果。
BaseOrchestrator    驱动「规划 → 执行 → 重规划」完整闭环。

所有 Base* 均为 typing.Protocol（runtime_checkable），结构化子类型无需继承。
ReplanDecision / DagGraphManager / OrchestratorResult 为具体类，可直接实例化或继承。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from .graph import DagNodeSpec, ready_node_ids
from .types import NodeStatus


# ── BaseGraphManager ──────────────────────────────────────────────────────────

@runtime_checkable
class BaseGraphManager(Protocol):
    """图与图节点管理器：DAG 运行时状态的单一权威来源。

    职责边界
    --------
    · 只管状态（status）和结构（deps）的读写；
    · 不了解节点的业务含义（描述、角色、prompt 等）。
    · ready_nodes() 封装调度逻辑，Orchestrator 直接轮询获取可并发执行的节点。
    · add_node / remove_node 支持 Replanner 的动态计划修补。
    · pause / resume 支持 Human-in-the-Loop 中断语义。
    """

    @property
    def plan_id(self) -> str:
        """计划唯一 ID。"""
        ...

    def all_node_ids(self) -> list[str]:
        """返回图中所有节点 ID（含已完成节点）。"""
        ...

    def node_deps(self, node_id: str) -> frozenset[str]:
        """返回 node_id 的直接前驱节点集合。"""
        ...

    def node_status(self, node_id: str) -> NodeStatus:
        """返回 node_id 的当前生命周期状态。"""
        ...

    def set_node_status(
        self,
        node_id: str,
        status: NodeStatus,
        **meta: Any,
    ) -> None:
        """更新 node_id 状态；meta 可携带 error / result / step_count 等上下文。"""
        ...

    def ready_nodes(self) -> list[str]:
        """返回处于 pending 且全部前驱已完成（done / skipped）的节点 ID 列表。"""
        ...

    def add_node(self, node_id: str, deps: frozenset[str]) -> None:
        """向图中添加一个新节点（初始状态为 pending）。Replanner patch 使用。"""
        ...

    def remove_node(self, node_id: str) -> None:
        """从图中移除节点，同时清理其他节点对它的依赖引用。Replanner patch 使用。"""
        ...

    def node_meta(self, node_id: str) -> dict[str, Any]:
        """返回 set_node_status() 时附带的 meta 信息（只读）。"""
        ...

    @property
    def is_paused(self) -> bool:
        """图是否处于暂停状态（Human-in-the-Loop）。"""
        ...

    def pause(self) -> None:
        """暂停图执行，等待人工干预。"""
        ...

    def resume(self) -> None:
        """解除暂停，允许等待中的节点继续执行。"""
        ...


# ── DagGraphManager ────────────────────────────────────────────────────────────

class DagGraphManager:
    """BaseGraphManager 的标准实现，基于 base/graph.py 纯算法。

    新集群直接实例化此类管理 DAG 运行时状态，无需自行实现调度逻辑。
    所有状态读写加 threading.Lock，可在多线程 / asyncio + executor 环境下安全使用。

    构造方式
    --------
    直接构造：DagGraphManager(plan_id, {node_id: frozenset(deps)})
    从 spec 构造：DagGraphManager.from_spec(spec)
    """

    def __init__(
        self,
        plan_id: str,
        nodes: dict[str, frozenset[str]],
    ) -> None:
        self._plan_id = plan_id
        self._lock = threading.Lock()
        self._deps: dict[str, frozenset[str]] = dict(nodes)
        self._statuses: dict[str, NodeStatus] = {
            n: NodeStatus.pending for n in nodes
        }
        self._meta: dict[str, dict[str, Any]] = {}
        self._paused = False

    @classmethod
    def from_spec(cls, spec: "BasePlanSpec") -> "DagGraphManager":
        """从 BasePlanSpec 构造图管理器（自动提取所有节点 ID 和依赖）。"""
        nodes = {n: spec.node_deps(n) for n in spec.all_node_ids()}
        return cls(plan_id=spec.plan_id, nodes=nodes)

    # ── 读接口 ────────────────────────────────────────────────────────────────

    @property
    def plan_id(self) -> str:
        return self._plan_id

    def all_node_ids(self) -> list[str]:
        with self._lock:
            return list(self._deps)

    def node_deps(self, node_id: str) -> frozenset[str]:
        with self._lock:
            return self._deps[node_id]

    def node_status(self, node_id: str) -> NodeStatus:
        with self._lock:
            return self._statuses[node_id]

    def node_meta(self, node_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._meta.get(node_id, {}))

    def ready_nodes(self) -> list[str]:
        """调用 base/graph.py 的 ready_node_ids，返回当前就绪节点列表。"""
        with self._lock:
            dag: list[DagNodeSpec] = [
                (n, self._deps[n], self._statuses[n])
                for n in self._deps
            ]
        return ready_node_ids(dag)

    # ── 写接口 ────────────────────────────────────────────────────────────────

    def set_node_status(
        self,
        node_id: str,
        status: NodeStatus,
        **meta: Any,
    ) -> None:
        with self._lock:
            self._statuses[node_id] = status
            if meta:
                self._meta[node_id] = meta

    def add_node(self, node_id: str, deps: frozenset[str]) -> None:
        """添加新节点（初始 pending）；用于 Replanner 的 add_task patch。"""
        with self._lock:
            self._deps[node_id] = deps
            self._statuses[node_id] = NodeStatus.pending

    def remove_node(self, node_id: str) -> None:
        """移除节点并清理其他节点对它的依赖引用；用于 Replanner 的 skip patch。"""
        with self._lock:
            self._deps.pop(node_id, None)
            self._statuses.pop(node_id, None)
            self._meta.pop(node_id, None)
            # 清理其他节点的依赖中对 node_id 的引用
            for nid in self._deps:
                if node_id in self._deps[nid]:
                    self._deps[nid] = self._deps[nid] - {node_id}

    # ── 暂停 / 恢复 ───────────────────────────────────────────────────────────

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._paused

    def pause(self) -> None:
        with self._lock:
            self._paused = True

    def resume(self) -> None:
        with self._lock:
            self._paused = False

    # ── 快照辅助 ──────────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, str]:
        """返回 {node_id: status.value} 的浅拷贝，用于快照 / 日志。"""
        with self._lock:
            return {n: s.value for n, s in self._statuses.items()}

    def progress(self) -> tuple[int, int]:
        """返回 (已完成节点数, 总节点数)。done / skipped 均计为完成。"""
        with self._lock:
            total = len(self._statuses)
            done = sum(
                1 for s in self._statuses.values()
                if s in (NodeStatus.done, NodeStatus.skipped)
            )
        return done, total


# ── BasePlanSpec ───────────────────────────────────────────────────────────────

@runtime_checkable
class BasePlanSpec(Protocol):
    """计划说明书：声明式地描述「要做什么」。

    职责边界
    --------
    · 只持有静态 / 半静态信息：目标描述、节点说明、依赖声明。
    · 不持有运行时状态（状态交给 BaseGraphManager）。
    · Orchestrator 从 spec 构造 DagGraphManager 后，执行期间只读取 spec。
    · apply_patch() 是唯一允许外部修改 spec 内容的入口，
      由 Orchestrator 在收到 Replanner 的 modify 决策后调用。

    说明书与图的关系
    ----------------
    spec.all_node_ids()       → 所有节点（声明式）
    spec.node_deps(id)        → 依赖关系（声明式）
    spec.node_description(id) → 节点任务说明（供 Executor 使用）

    DagGraphManager.from_spec(spec) → 运行时图状态（由 Orchestrator 构造）
    """

    @property
    def plan_id(self) -> str:
        """唯一计划 ID，由 Orchestrator 在 run() 开始时赋值，之后只读。"""
        ...

    @property
    def title(self) -> str:
        """计划标题，用于日志与 UI 显示。"""
        ...

    @property
    def objective(self) -> str:
        """目标描述（一到两句话），供 Replanner 阅读决策。"""
        ...

    def all_node_ids(self) -> list[str]:
        """返回该计划中所有节点的 ID。"""
        ...

    def node_deps(self, node_id: str) -> frozenset[str]:
        """返回 node_id 的声明式直接前驱节点集合。"""
        ...

    def node_description(self, node_id: str) -> str:
        """返回 node_id 对应的任务描述，供 NodeExecutor 理解要做什么。"""
        ...

    def apply_patch(self, patch: Any) -> None:
        """将 Replanner 的补丁指令应用到 spec（更新描述、新增/移除节点等）。

        patch 类型由集群自行定义（如 HumanPatch），Orchestrator 透传不解析。
        apply_patch() 只修改说明书内容；DagGraphManager 的结构变更由
        Orchestrator 在调用 apply_patch() 后同步到图管理器。
        """
        ...


# ── BasePlanner ────────────────────────────────────────────────────────────────

@runtime_checkable
class BasePlanner(Protocol):
    """规划器：将自然语言目标转化为可执行的 DAG 计划说明书。

    plan() 为 async，允许内部在线程池中运行同步 LLM 推理；
    step_callback(index, thought, action, observation) 用于流式推送规划过程中的 TAO 步骤。

    context 携带可选的上游信息（前序集群产出、用户偏好等），
    各集群实现可读取自己理解的字段，忽略其余字段。

    解析或校验失败时应直接 raise；Orchestrator 捕获异常并标记生命周期为 failed。
    """

    async def plan(
        self,
        goal: str,
        *,
        context: dict[str, Any] | None = None,
        step_callback: Callable[[int, str, str, str], None] | None = None,
    ) -> BasePlanSpec:
        """为 goal 生成计划说明书，返回可被 Orchestrator 调度的 BasePlanSpec。"""
        ...


# ── ReplanDecision ─────────────────────────────────────────────────────────────

@dataclass
class ReplanDecision:
    """重规划决策基类。

    Orchestrator 核心只检查 decision 和 conclusion；
    具体集群通过继承添加域字段（patches / confidence / trigger 等）。

    decision 取值
    -------------
    done     所有目标已达成；conclusion 提供最终结论。
    continue 计划正常推进，无需修改。
    modify   需要调整计划；具体补丁由子类字段携带，Orchestrator 调用 spec.apply_patch()。
    abort    不可恢复失败；conclusion 提供当前最佳答案。
    """

    decision: str       # "done" | "continue" | "modify" | "abort"
    conclusion: str = ""
    reason: str = ""


# ── BaseReplanner ──────────────────────────────────────────────────────────────

@runtime_checkable
class BaseReplanner(Protocol):
    """重规划器：根据当前计划状态决定下一步行动。

    replan() 同时接收 spec（说明书）和 graph（运行时图状态），
    因为重规划决策通常既需要理解「计划要做什么」，也需要知道「执行到哪儿了」。

    触发器（trigger）为域定义字符串，例如：
      "on_task_failed" / "on_module_complete" / "on_human_request" / "on_plan_complete"

    should_trigger() 让 Replanner 声明关心哪些触发器，Orchestrator 据此决定调用时机。
    """

    async def replan(
        self,
        spec: BasePlanSpec,
        graph: BaseGraphManager,
        *,
        trigger: str,
        cycle: int = 0,
    ) -> ReplanDecision:
        """分析当前执行状态，返回重规划决策。

        spec   提供节点描述和目标，帮助 Replanner 理解语义。
        graph  提供运行时状态（哪些节点 done / failed / pending）。
        cycle  本次编排中已触发的重规划次数，供 Replanner 决策是否终止。
        """
        ...

    def should_trigger(self, trigger: str) -> bool:
        """返回 True 表示该 trigger 应触发一次 replan() 调用。"""
        ...


# ── BaseNodeExecutor ───────────────────────────────────────────────────────────

@runtime_checkable
class BaseNodeExecutor(Protocol):
    """节点执行器：执行 DAG 中的单个节点，返回原始输出。

    职责边界
    --------
    · 接收 node_id 和只读的 BasePlanSpec（获取节点描述、工具包等信息）。
    · 不接触 BaseGraphManager，不修改节点状态。
    · 执行失败应直接 raise；Orchestrator 捕获异常并调用 graph.set_node_status(failed)。
    · step_callback 用于将执行过程中的 TAO 步骤实时推送给调用方。
    """

    async def execute(
        self,
        node_id: str,
        spec: BasePlanSpec,
        *,
        step_callback: Callable[[int, str, str, str], None] | None = None,
    ) -> Any:
        """执行 node_id 对应的任务，返回原始输出（str / dict / 任意值）。

        step_callback(index, thought, action, observation) 在每个 TAO 步骤时调用。
        """
        ...


# ── Events ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OrchestratorEvent:
    """编排生命周期事件基类。

    kind 为点分层级命名空间字符串，标准事件名：
      "plan.start"      "plan.complete"    "plan.abort"
      "task.start"      "task.complete"    "task.failed"    "task.skipped"
      "replan.start"    "replan.complete"
      "snapshot.saved"  "graph.pause"      "graph.resume"

    具体集群可继承此类添加字段（如 task_profile、node_meta 等）。
    subscribe() 回调的类型标注接受 OrchestratorEvent；子类自动兼容。
    """

    plan_id: str
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


# ── OrchestratorResult ─────────────────────────────────────────────────────────

@dataclass
class OrchestratorResult:
    """编排完成后的最终结果。

    status  "done" | "failed" | "aborted"
    answer  最终结论文本（由 Replanner.conclusion 或 spec 的 conclusion 字段填入）
    error   异常信息（status == "failed" 时有值）
    spec    最终计划说明书（若 Planner 阶段即失败则为 None）
    graph   最终图状态快照（同上）
    """

    plan_id: str
    status: str
    answer: str = ""
    error: str | None = None
    spec: BasePlanSpec | None = None
    graph: BaseGraphManager | None = None


# ── BaseOrchestrator ───────────────────────────────────────────────────────────

@runtime_checkable
class BaseOrchestrator(Protocol):
    """编排器：驱动「规划 → 执行 → 重规划」完整闭环。

    职责
    ----
    1. 调用 BasePlanner.plan(goal) → BasePlanSpec
    2. 用 DagGraphManager.from_spec(spec) 构造运行时图
    3. 循环：graph.ready_nodes() → 并发调用 BaseNodeExecutor.execute()
       → graph.set_node_status(done / failed)
    4. 按触发器调用 BaseReplanner.replan(spec, graph, trigger=...) → ReplanDecision
       → decision == "modify"：spec.apply_patch(patch) + 同步 graph
       → decision == "done" / "abort"：结束
    5. 通过 subscribe() 向订阅者推送 OrchestratorEvent（用于 WebUI / 日志）

    每个 DAG 集群（plan / doc / code …）提供自己的 Orchestrator 实现；
    共用的图算法和调度逻辑来自 DagGraphManager / base/graph.py；
    域特定逻辑（prompt 格式、IR 类型、事件字段）封装在各集群目录内，彼此不耦合。
    """

    async def run(self, goal: str) -> OrchestratorResult:
        """为 goal 执行完整的规划 + 执行 + 重规划闭环。"""
        ...

    def subscribe(self, callback: Callable[[OrchestratorEvent], None]) -> None:
        """注册生命周期事件回调（多个订阅者按注册顺序依次调用）。"""
        ...

    def progress(self) -> tuple[int, int]:
        """返回 (已完成节点数, 总节点数)，run() 运行期间可轮询。
        run() 未开始或已结束时返回 (0, 0)。
        """
        ...
