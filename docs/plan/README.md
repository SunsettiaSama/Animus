# agent.flow — DAG 规划与编排

`agent.flow` 是多智能体编排层，提供两个协作层级：

- **base 层**：与具体 Planner/Replanner 实现无关的通用 DAG 引擎（`DagOrchestrator`、`AtomicPlanner`、`ManifestPlanSpec`）。
- **cluster 层**：基于 TaoLoop 的 Cluster Planner/Replanner，使用 Markdown 计划语言与 `PlanDocument` IR。

---

## 整体工作流

### 完整路径（Cluster + Base）

```
用户目标（goal）
        │
        ▼
[Cluster] PlannerAgent.run(goal)
        │   使用 TaoLoop 生成 Markdown 计划文本
        │   PlanParser.parse() → PlanDocument（含 N 个 PlanTask）
        │   PlanValidator 检查（重复 ID / 未知依赖 / 自引用 / 环检测）
        │
        ▼
[Cluster] FlowOrchestrator
        │   _task_to_manifest(task) → NodeManifest（每个 PlanTask → 节点声明）
        │   ManifestPlanSpec（N 节点声明图）
        │
        ▼
[Base] DagOrchestrator._execute(spec, graph, budget)
        │
        ├─ 并发主循环（asyncio.gather）
        │       每个节点独立协程，等待依赖后执行
        │       │
        │       ▼
        │   AtomicPlanner.assess(manifest, budget)
        │       ├─ is_atomic() 确定性快速路径（无 LLM）
        │       │
        │       ├─ atomic  → SubAgentManifestExecutor.run(manifest, inputs)
        │       │               └─ SubAgentRunner → TaoLoop（携带 tool_package）
        │       │
        │       ├─ flat    → 展开为同层兄弟节点，动态注册到同一 DAG
        │       │
        │       └─ nested  → 起子 DagOrchestrator（budget.descend()），
        │                     将出口节点结果接回父节点
        │
        └─ Replanner 触发
                on_task_failed   → ReplannerAgent.replan() → patches → spec.apply_patch()
                on_plan_complete → ReplannerAgent.replan() → done / abort / modify
```

### 最小路径（仅 Base，无初始 Planner）

```
goal
  │
  ▼
ManifestPlanSpec.single_node(goal)
  │   生成单节点种子图（task_id="root"）
  ▼
DagOrchestrator._execute(...)
  │
  ▼
AtomicPlanner.assess(root_manifest)
  │   LLM 决策：root 是否需要拆分？
  ├─ atomic  → 直接执行
  ├─ flat    → 展开为 N 个同层节点，各自递归 assess
  └─ nested  → 起子图，递归 assess
```

---

## 组件详解

### 1. AtomicPlanner（原子规划层）

**职责**：对单个 `NodeManifest` 决定拓扑类型，是原子还是需要展开。

**判断流程**：

```
AtomicPlanner.assess(manifest, budget)
        │
        ├─ is_atomic(manifest, budget)  ← 确定性检查（无 LLM）
        │       条件（全部满足则 atomic）：
        │       · budget.exhausted（depth=0，强制原子）
        │       · manifest.sub_manifests 非空（已预先展开）
        │       · input_contract 和 output_contract 均已填写
        │       · max_steps ≤ budget.max_atom_steps
        │       · description 不含复合职责关键词
        │       返回 True → TopologyDecision(atomic, "passed is_atomic()")
        │
        ├─ LLM 调用（_assess_sync via thread pool）
        │       System: AtomicPlanner prompt（含 budget 约束）
        │       User:   manifest 字段 + context
        │       输出:   JSON → TopologyDecision
        │
        └─ AtomicReviewer.review()（如 budget.review_enabled）
                → ReviewOutcome
                approved=True          → 使用原决策
                approved=False, revised → 使用修订版
                approved=False, None   → 降级为 atomic
```

**拓扑类型**：

| 类型 | 含义 | 操作 |
|------|------|------|
| `atomic` | 单一职责，可直接执行 | `SubAgentManifestExecutor.run()` |
| `flat` | 拆为同层兄弟节点 | 注册到当前 DAG，与其他节点共享调度 |
| `nested` | 自包含子系统 | 起独立子 `DagOrchestrator`，对外暴露 `output_node_id` |

**flat vs nested 选择准则**：
- **flat**：子任务需要与当前 DAG 中**其他节点**协调（共享数据、有外部依赖）。
- **nested**：子任务内聚、对外呈现清晰 I/O 界面，内部细节无需暴露。

---

### 2. AtomicReviewer（拓扑决策审查）

**职责**：对 `AtomicPlanner` 的 `TopologyDecision` 做一次自洽性审查。

**审查内容**：
1. **I/O 链式闭合**：顺序边 A → B 中，A.output_contract 能否满足 B.input_contract。
2. **依赖正确性**：`depends_on` 中的 task_id 均存在且无环。
3. **类型适当性**：flat/nested 语义是否正确使用；nested 必须有非空 `output_node_id`。
4. **宽度约束**：sub_nodes 数量不超过 `budget.max_width`。
5. **拆分价值**：拆分是否有实质意义（非重命名、非单子节点复制）。

**输出**：`ReviewOutcome`（`approved / critique / revised`）。

审查只在 `budget.review_enabled = True`（即 `max_review_rounds > 0`）时激活。

---

### 3. DecompositionBudget（递归展开预算）

```python
@dataclass(frozen=True)
class DecompositionBudget:
    max_depth: int = 3       # 最大嵌套深度（0 = 强制原子）
    max_width: int = 8       # 同层最多展开节点数
    max_atom_steps: int = 5  # 原子节点最大预期 TAO 步数
    max_review_rounds: int = 1  # 审查轮次（0 = 禁用 reviewer）
```

进入每层嵌套时，`budget.descend()` 将 `max_depth - 1` 后向下传递。`budget.exhausted`（`max_depth == 0`）时 `AtomicPlanner` 直接返回 atomic，防止无限递归。

---

### 4. ManifestPlanSpec + ManifestPatch

`ManifestPlanSpec` 是 `DagOrchestrator` 的唯一声明式源：

```python
class ManifestPlanSpec:
    plan_id: str
    title: str
    objective: str
    _manifests: dict[str, NodeManifest]   # task_id → 节点声明

    # 工厂
    @classmethod
    def single_node(cls, goal: str) -> ManifestPlanSpec   # 单节点 bootstrap

    # 访问
    def manifest(self, node_id: str) -> NodeManifest
    def all_node_ids(self) -> list[str]
    def node_deps(self, node_id: str) -> frozenset[str]

    # Replanner 修补
    def apply_patch(self, patch: ManifestPatch) -> None
```

`ManifestPatch` 的可操作字段：

| 字段 | 类型 | 作用 |
|------|------|------|
| `add_manifests` | `tuple[NodeManifest, ...]` | 新增或覆盖同 task_id 节点 |
| `remove_ids` | `tuple[str, ...]` | 删除节点 |
| `update_descriptions` | `dict[str, str]` | 更新节点 description |
| `add_deps` | `dict[str, tuple[str,...]]` | 追加依赖边 |

---

### 5. NodeManifest（节点声明）

`AtomicPlanner` 评估的对象，同时是 `SubAgentManifestExecutor` 执行的依据：

| 字段 | 类型 | 来源/用途 |
|------|------|-----------|
| `task_id` | str | DAG 节点唯一标识（snake_case） |
| `description` | str | 自然语言任务说明，传给 executor LLM |
| `depends_on` | tuple[str,...] | 上游节点 ID，调度层使用 |
| `input_contract` | str | 对上游输入格式的期望（AtomicPlanner 推理依赖合法性） |
| `output_contract` | str | 产出物约束（executor 知晓目标格式；reviewer 校验） |
| `tool_package` | str\|None | 工具包名（"executor"/"researcher"/"code"/"full" 等） |
| `max_steps` | int\|None | TAO 最大步数上限 |
| `system_note` | str | 追加到 executor system prompt 的任务级约束 |
| `observation_mode` | ObservationMode | `distilled`（默认）或 `full` |
| `topology` | TopologyKind | 拓扑类型（AtomicPlanner 填写） |
| `topology_reason` | str | AtomicPlanner 的决策理由（审计用） |
| `sub_manifests` | tuple[NodeManifest,...] | flat/nested 时的子节点列表 |
| `output_node_id` | str | nested 子图的出口节点 task_id |
| `tags` | dict[str,str] | 任意扩展标注，不影响执行逻辑 |

---

### 6. Cluster 层 PlannerAgent

`PlannerAgent` 通过 TaoLoop 运行，将用户目标转换为结构化 `PlanDocument`：

```
PlannerAgent.run(goal)
    │
    ├─ _build_tao_loop(cfg, llm_cfg_path, _PLANNER_SYSTEM)
    │       工具：scratchpad（可选 web_search/knowledge_hybrid_search）
    │
    ├─ TaoLoop.stream(_DRAFT_PROMPT + goal)
    │       LLM 输出 Markdown 计划（含草稿和最终版本）
    │
    ├─ PlanParser.parse(answer) → PlanDocument
    │       解析 Markdown 注解：
    │         `profile:researcher`  `max_steps:15`
    │         `depends_on:task_id`  `parallel:true`
    │
    ├─ PlanValidator.validate(doc)
    │       检查：重复 ID / 未知依赖 / 自引用 / 拓扑环 / Objective 非空
    │
    └─ 返回 AgentResult(output=PlanDocument)
```

`PlanDocument` 结构：

| 字段 | 说明 |
|------|------|
| `plan_id` | UUID |
| `title` | 计划标题（LLM 自动生成） |
| `objective` | 目标描述（`## Objective` 小节） |
| `modules` | `list[PlanModule]`（视觉分组，不影响执行顺序） |
| `metadata` | `max_replan_cycles`, `timeout`, `paused` |
| `replan_notes` | Replanner 追加的备注 |
| `conclusion` | 最终结论（由 Replanner decision=done 填写） |

`PlanTask` 可修改字段（运行前）：

| 方法 | 可覆盖字段 |
|------|-----------|
| `doc.set_params(task_id, profile=..., max_steps=...)` | `profile`, `max_steps`, 任意 `params` |
| `doc.update_task(task_id, ...)` | 任意 dataclass 字段（async，线程安全） |

---

### 7. Cluster 层 ReplannerAgent

**触发条件**（在 `ReplannerConfig.triggers` 中配置）：

| 触发器 | 时机 |
|--------|------|
| `on_task_failed` | 任何节点执行失败后 |
| `on_module_complete` | 一个模块的所有任务完成后 |

**输入**：`ReplannerInputBuilder` 组装执行上下文，包含：
- 已完成任务摘要（含 step_count 和 result 摘要）
- 失败任务详情（含 error、last_steps、retry_count）
- 剩余计划（pending/paused 任务的 Markdown）
- 触发信息（trigger + cycle 编号）

**输出**：`ReplanDecision`

| 字段 | 类型 | 说明 |
|------|------|------|
| `decision` | str | `done`/`continue`/`modify`/`abort` |
| `confidence` | float | 0.0–1.0 |
| `reason` | str | 决策理由 |
| `patches` | list[HumanPatch] | op=`skip`/`set_params`/`add_task` |
| `conclusion` | str | decision=done/abort 时的最终答案 |

**Patch 操作**：

| op | 效果 |
|----|------|
| `skip` | 标记任务为 skipped（可 cascade） |
| `set_params` | 覆盖 profile / max_steps / system_note |
| `add_task` | 动态追加新任务节点 |

---

### 8. NodeRegistry（执行器/规划器工厂）

`register_defaults(llm_cfg_path)` 向全局 `NodeRegistry` 注入：

| 注册项 | 实现 |
|--------|------|
| `executor_factory` | `lambda pkg: SubAgentManifestExecutor(llm_cfg_path)` |
| `atomic_planner_factory` | `lambda cfg: AtomicPlanner(llm_call, reviewer)` |
| `atomic_reviewer_factory` | `lambda cfg: AtomicReviewer(llm_call)` |
| `known_packages` | 所有 `BUILTIN_PACKAGES` 名称 |

---

## 内置工具包（ToolPackage）

| 包名 | 工具集 | 适用场景 |
|------|--------|---------|
| `planner` | note_write/read/delete + web_search + knowledge_hybrid_search | 主 agent 规划推理 |
| `executor` | calculator + get_datetime + web_search + unit_converter + word_count | 通用执行 |
| `researcher` | web_search + web_fetch + knowledge_hybrid_search/save/list | 信息研究 |
| `analyst` | calculator + unit_converter + datetime + python_run + json_query + regex_extract | 数据分析 |
| `code` | python_run + file_read/write/list/exists | 代码执行 |
| `filesystem` | file_read/write/list/exists | 文件操作 |
| `knowledge` | knowledge_hybrid_search/save/list | 知识库操作 |
| `network` | web_search + web_fetch + http_request | 网络请求 |
| `full` | 所有已实现工具 | 测试与研究型任务 |

---

## 配置

### DecompositionBudget

```python
DecompositionBudget(
    max_depth=3,          # 嵌套深度上限
    max_width=8,          # 同层展开节点数上限
    max_atom_steps=5,     # 原子节点最大预期 TAO 步数
    max_review_rounds=1,  # AtomicReviewer 启用（0 = 禁用）
)
```

### PlannerConfig（Cluster 层）

```python
PlannerConfig(
    mode="auto",              # "auto" | "interactive"
    tools=["scratchpad"],     # Planner TaoLoop 可用工具
    allow_search=False,       # 是否追加 web_search / knowledge_hybrid_search
    max_steps=8,              # TaoLoop 最大步数
    max_retries=3,            # Markdown 解析失败重试次数
    memory_short_term=True,
    memory_long_term=False,
)
```

### ReplannerConfig（Cluster 层）

```python
ReplannerConfig(
    triggers=["on_task_failed", "on_module_complete"],
    max_cycles=3,
    confidence_threshold=0.0,
    result_summary_max_chars=300,
    failed_last_steps=3,      # 失败任务最后 N 条 step 纳入 context
)
```

### DagOrchestrator 参数

```python
DagOrchestrator(
    planner=None,             # 实现 plan(goal)->ManifestPlanSpec；None 则 single_node bootstrap
    atomic_planner=atomic,    # AtomicPlanner 实例（register_defaults 后从 registry 取）
    registry=reg,             # NodeRegistry；None 取全局单例
    replanner=None,           # BaseReplanner；None 跳过重规划
    budget=DecompositionBudget(),
    parallel_limit=0,         # 0 = 不限制
    replanner_triggers={"on_task_failed", "on_plan_complete"},
)
```

---

## 快速开始

### 最小路径（无初始 Planner）

```python
from agent.flow.base.defaults import register_defaults
from agent.flow.base.registry import get_registry
from agent.flow.base.dag_orchestrator import DagOrchestrator
from agent.flow.base.budget import DecompositionBudget

register_defaults("config/llm_core/config.yaml")
reg = get_registry()
atomic = reg.build_atomic_planner("config/llm_core/config.yaml")

orch = DagOrchestrator(atomic_planner=atomic, registry=reg)
result = asyncio.run(orch.run("列出 3 条学习 Python asyncio 的步骤"))
print(result.answer)
```

### 单节点直接执行（跳过 AtomicPlanner）

```python
from agent.flow.base.components.node_spec import NodeManifest, ObservationMode
from agent.flow.base.defaults import register_defaults, SubAgentManifestExecutor

register_defaults("config/llm_core/config.yaml")
manifest = NodeManifest(
    task_id="my_task",
    description="搜索 Python asyncio 最佳实践并整理为 3 条建议",
    tool_package="researcher",
    max_steps=8,
    input_contract="无上游依赖",
    output_contract="3 条结构化建议",
    observation_mode=ObservationMode.distilled,
)
executor = SubAgentManifestExecutor("config/llm_core/config.yaml")
answer = executor.run(manifest, inputs={})
print(answer)
```

### 完整 Cluster 路径

```python
from agent.flow.cluster.config import FlowConfig
from agent.flow.cluster.orchestrator import FlowOrchestrator

cfg = FlowConfig(llm_cfg_path="config/llm_core/config.yaml")
orch = FlowOrchestrator(cfg.orchestrator, cfg.llm_cfg_path)

def on_event(ev):
    print(f"[{ev['type']}]", ev.get("task_id", ""))

orch.subscribe(on_event)
result = asyncio.run(orch.run("从多个 RSS 源抓取文章并生成摘要报告"))
print(result.conclusion)
```

---

## 目录结构

```
src/agent/flow/
├── base/                        # 通用 DAG 引擎（无 TaoLoop 直接依赖）
│   ├── __init__.py
│   ├── budget.py                # DecompositionBudget + TopologyKind + is_atomic()
│   ├── dag_orchestrator.py      # DagOrchestrator（主引擎）
│   ├── defaults.py              # register_defaults() + SubAgentManifestExecutor
│   ├── orchestration.py         # DagGraphManager + OrchestratorEvent + 协议接口
│   ├── plan_spec.py             # ManifestPlanSpec + ManifestPatch
│   ├── registry.py              # NodeRegistry（执行器/规划器工厂）
│   └── components/
│       ├── atomic_planner.py    # AtomicPlanner
│       ├── atomic_reviewer.py   # AtomicReviewer
│       ├── node_spec.py         # NodeManifest + TopologyDecision + ReviewOutcome
│       ├── observation.py       # ObservationMode
│       ├── protocols.py         # BaseAtomicPlanner / ManifestExecutor / NodeVerifier
│       └── runtime.py           # RunnableNode + NodeResult
│
└── cluster/                     # TaoLoop 驱动的 Cluster 层
    ├── __init__.py
    ├── config.py                # FlowConfig / OrchestratorConfig / PlannerConfig / ReplannerConfig
    ├── document.py              # PlanDocument + PlanTask + PlanModule + PlanParser + PlanValidator
    ├── event.py                 # PlanEvent 系列（含 SSE 序列化）
    ├── patch.py                 # HumanPatch + PatchOp
    ├── channel.py               # HumanEditChannel（shadow copy 文件监视）
    ├── snapshot.py              # SnapshotStore
    ├── log.py                   # PlanLogger（JSONL）
    ├── executor.py              # ExecutorAgent
    ├── planner.py               # PlannerAgent + ConvPlanner
    ├── replanner.py             # ReplannerAgent
    ├── orchestrator.py          # FlowOrchestrator
    └── result.py                # PlanResult
```
