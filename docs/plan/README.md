# plan 模块

Plan-and-Execute 多智能体编排层，支持 Markdown 计划语言、异步 DAG 调度、增量 Replanner、人类编辑通道（Human-in-the-Loop）、文件资源锁、计划快照回滚与结构化日志。

---

## 架构总览

```
用户目标（question）
        │
        ▼
  PlanOrchestrator.run(question)
        │
        ├─ PlannerAgent.plan(question)
        │       └─ LLM 生成 Markdown 计划
        │               └─ PlanParser.parse() → PlanDocument（IR）
        │                       └─ PlanValidator（重复/未知依赖/自引用/拓扑环检测）
        │
        ├─ SnapshotStore.save()  ← 规划完成后立即保存初始快照
        │
        ├─ _dispatch_all(doc)    ← 异步 DAG 执行引擎
        │       │
        │       ├─ 每个 task 启动独立协程（asyncio.create_task）
        │       │       ├─ 等待依赖完成（asyncio.Event per task）
        │       │       ├─ 等待计划恢复（doc._resume_event）
        │       │       ├─ 排干 HumanEditChannel patch 队列（apply diffs）
        │       │       ├─ 资源守卫（asyncio.Condition，writes 声明）
        │       │       ├─ 并发限制（asyncio.Semaphore）
        │       │       └─ ExecutorAgent.run(task) → CrewRunner → TaoLoop
        │       │
        │       └─ ReplannerAgent 触发（失败/模块完成/人类请求/超时/目标漂移）
        │               └─ 生成增量 PlanPatch → PlanDocument 原地修补
        │
        └─ PlanResult（plan_id / status / answer / task_results）
```

---

## 目录结构

```
src/plan/
├── __init__.py       # 导出所有公共符号
├── config.py         # PlannerConfig / ReplannerConfig / OrchestratorConfig / LogConfig
├── document.py       # PlanDocument IR + PlanParser + PlanValidator + CycleDetector
├── event.py          # PlanEvent 联合类型（10 种事件）
├── patch.py          # PatchOp + HumanPatch + PlanDiff
├── channel.py        # HumanEditChannel（shadow copy 文件监视）
├── snapshot.py       # SnapshotStore + PlanSnapshot
├── log.py            # PlanLogger（JSONL 结构化日志）
├── executor.py       # ExecutorAgent（单任务执行器）
├── planner.py        # PlannerAgent + ConvPlanner
├── replanner.py      # ReplannerAgent
├── orchestrator.py   # PlanOrchestrator（主驱动）
└── result.py         # PlanResult
```

---

## 计划语言（Markdown）

`PlannerAgent` 输出标准 Markdown，`PlanParser` 将其解析为 `PlanDocument` IR。

```markdown
# objective: 分析竞品市场并生成报告

## module: research
- task_id: search_web
  description: 搜索互联网上关于竞品的最新动态
  profile: researcher
  depends_on: []
  writes: [data/raw.json]

- task_id: analyze_data
  description: 对搜索结果进行量化分析
  profile: analyst
  depends_on: [search_web]
  writes: [data/analysis.json]

## module: report
- task_id: write_report
  description: 综合研究结果撰写最终报告
  profile: minimal
  depends_on: [analyze_data]
  writes: [report/final.md]
```

### 关键字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `objective` | str | 计划目标（H1 标题）|
| `module` | str | 模块名（H2 标题），将任务分组 |
| `task_id` | str | 唯一任务标识符（全局不重复）|
| `description` | str | 任务描述，传给 ExecutorAgent |
| `profile` | str | 执行 profile（`minimal` / `researcher` / `analyst` / 自定义）|
| `depends_on` | list[str] | 依赖的 task_id 列表（构成 DAG 边）|
| `writes` | list[str] | 声明写入的外部资源路径（用于资源锁）|
| `parallel` | bool | 是否允许与其他任务并行（默认 true）|
| `params` | dict | 传给 ExecutorAgent 的额外参数 |

---

## 核心数据结构

### `PlanDocument`

```python
@dataclass
class PlanDocument:
    plan_id: str
    metadata: PlanMetadata         # objective, created_at, paused
    modules: dict[str, PlanModule] # module_name → PlanModule
    _lock: asyncio.Lock            # 状态写入保护
    _resume_event: asyncio.Event   # 暂停/恢复信号
```

#### 主要方法

| 方法 | 说明 |
|---|---|
| `all_tasks()` | 按模块顺序返回所有 `PlanTask` |
| `get_task(task_id)` | 按 ID 查找任务 |
| `to_markdown()` | 转换为 Markdown 字符串（含 `writes:` 注解）|
| `to_dict()` / `from_dict()` | 序列化 / 反序列化（用于快照）|
| `pause()` / `resume()` | 暂停/恢复（操作 `_resume_event`）|

### `PlanTask`

```python
@dataclass
class PlanTask:
    task_id: str
    description: str
    module: str = ""
    profile: str = "minimal"
    max_steps: int | None = None
    depends_on: list[str] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)   # 资源锁声明
    parallel: bool = False
    status: TaskStatus = TaskStatus.pending
    result: str | None = None
    error: str | None = None
    params: dict = field(default_factory=dict)
    execution_ctx: TaskExecutionContext | None = None
```

### `TaskStatus`

```python
class TaskStatus(str, Enum):
    pending   = "pending"
    running   = "running"
    done      = "done"
    failed    = "failed"
    skipped   = "skipped"
```

---

## 验证（`PlanValidator` + `CycleDetector`）

`PlanValidator.validate(doc)` 在计划执行前检查：

1. **重复 task_id**：同一计划内所有任务 ID 唯一
2. **未知依赖**：`depends_on` 中引用的 task_id 必须存在于计划中
3. **自引用**：任务不能依赖自身
4. **拓扑环**：使用**三色 DFS**（`CycleDetector`）检测有向环，发现环则 raise `PlanValidationError` 并报告环路径

---

## 异步 DAG 调度（`PlanOrchestrator._dispatch_all`）

采用**事件驱动动态就绪**模型，每个任务一个 `asyncio.Event`：

```
for each task:
    create asyncio.create_task(run_when_ready(task))

run_when_ready(task):
    # 1. 等待所有依赖完成
    for dep_id in task.depends_on:
        await done_events[dep_id].wait()

    # 2. 等待计划恢复（如已暂停）
    await doc._resume_event.wait()

    # 3. 排干 HumanEditChannel patch 队列
    for patch in channel.drain():
        PlanDiff.apply(doc, patch)

    # 4. 资源守卫（writes 字段）
    async with resource_cond:
        while in_use_writes & set(task.writes):
            await resource_cond.wait()
        in_use_writes.update(task.writes)

    # 5. 并发限制
    async with semaphore:
        result = await executor.run(task)

    # 6. 释放资源
    async with resource_cond:
        in_use_writes.difference_update(task.writes)
        resource_cond.notify_all()

    # 7. 标记完成，触发后续任务
    done_events[task.task_id].set()
```

### 资源锁机制（`writes` 字段）

- 每个 `PlanTask` 可声明 `writes: [path1, path2, ...]`，表示该任务会写入这些外部文件/资源。
- 编排器在调度时检测 `writes` 集合重叠，有重叠的任务会排队等待，避免并发写冲突。
- `writes` 字段由 **Planner / Replanner** 在规划阶段根据任务语义填写；编排器只做透明的守卫，不主动推断。

---

## 人类编辑通道（`HumanEditChannel`）

实现"影子副本"（shadow copy）机制：

```
PlanDocument ──→ materialize() ──→ shadow.md（本地文件）
                                         │
                              用户直接编辑 shadow.md
                                         │
watch() 检测文件变更 ──→ sync() ──→ PlanDiff.compute(old, new)
                                         │
                              patch 入队（channel._queue）
                                         │
编排器在安全点 ──→ channel.drain() ──→ PlanDiff.apply(doc, patch)
```

- `sync()` 使用 `PlanParser.parse(text, strict=False)` 解析用户编辑，允许不完整的 Markdown（缺 objective 或 modules 时使用默认值，而非报错）。
- `watch()` 在文件变更时调用 `doc.pause()` / `doc.resume()`，确保 patch 在单一安全点应用，不中断正在运行的任务。

---

## 快照（`SnapshotStore`）

```python
store = SnapshotStore(base_dir=".react/plan/snapshots")

# 保存
snap_id = store.save(doc, label="after_replan")

# 列出
snapshots = store.list(plan_id)

# 加载
doc = store.load(snapshot_id)

# 回滚（同时重置 running/failed 任务至 pending，清除 execution_ctx）
doc = store.rollback(snapshot_id)
```

快照以 JSON 格式存储于 `.react/plan/snapshots/<plan_id>/<snap_id>.json`。

---

## 结构化日志（`PlanLogger`）

JSONL 格式，存储于 `.react/plan/logs/<plan_id>.jsonl`。

```python
logger = PlanLogger(plan_id, base_dir=".react/plan/logs")

await logger.info("task_start", task_id="t1", profile="researcher")
await logger.error("task_failed", task_id="t1", error="timeout")

# 同步读取（含过滤）
records = logger.read(level_min=LogLevel.INFO, task_id="t1", n=50)

# 异步读取
records = await logger.read_async(task_id="t1", n=50)
```

---

## 事件流（`PlanEvent`）

`PlanOrchestrator` 在执行过程中发射事件，可通过 WebUI SSE 端点（`/api/plan/stream`）实时消费：

| 事件类型 | 触发时机 |
|---|---|
| `PlanStartEvent` | 编排开始 |
| `TaskStartEvent` | 任务提交到执行队列 |
| `TaskRunningEvent` | 任务进入 ExecutorAgent（semaphore 获取后）|
| `TaskCompleteEvent` | 任务执行成功 |
| `TaskFailedEvent` | 任务执行失败 |
| `TaskSkippedEvent` | 任务被跳过 |
| `ReplanEvent` | Replanner 触发重规划 |
| `HumanPatchEvent` | 应用了人类编辑 patch |
| `SnapshotEvent` | 保存了快照 |
| `PlanCompleteEvent` | 计划全部完成 |
| `PlanAbortEvent` | 计划异常终止 |

---

## Replanner（`ReplannerAgent`）

### 触发条件

| 触发器 | 说明 |
|---|---|
| `on_task_failure` | 任何任务失败时 |
| `on_module_complete` | 一个模块的所有任务完成时 |
| `on_human_request` | 人类显式请求重规划 |
| `on_timeout` | 任务超时 |
| `on_goal_drift` | LLM 判断目标发生漂移 |
| `on_conflict` | 检测到资源冲突 |

### 增量输入格式

Replanner 接收以下增量上下文：

```
[已完成任务摘要]
task_id: xxx | status: done | result: ...
task_id: yyy | status: failed | error: ...

[失败任务上下文]
task_id: yyy
execution_ctx: { thought/action/observation traces }

[剩余计划（Markdown）]
## module: remaining_work
- task_id: zzz
  ...
```

Replanner 输出 `PlanPatch`（JSON），由编排器原地修补 `PlanDocument`。

---

## 对话式规划（`ConvPlanner`）

`ConvPlanner` 继承 `ConvLoop`，提供多轮对话式计划生成：

```python
conv = ConvPlanner(llm=llm, cfg=planner_cfg)
doc = await conv.plan_interactive(question)
```

对话过程中用户可反复提供反馈，LLM 逐轮完善计划，直到用户确认或对话达到轮次上限。最终输出经 `PlanParser.parse()` 转换为 `PlanDocument`。

---

## 配置

```python
@dataclass
class OrchestratorConfig:
    parallel_limit: int = 4           # 最大并发执行任务数
    replan_cfg: ReplannerConfig = ... # Replanner 触发配置
    log_cfg: LogConfig = ...          # 日志配置
    snapshot_on_replan: bool = True   # 重规划前自动快照
    snapshot_on_complete: bool = True # 完成后自动快照

@dataclass
class ReplannerConfig:
    triggers: list[str] = field(default_factory=lambda: ["on_task_failure"])
    max_replan_rounds: int = 3

@dataclass
class PlannerConfig:
    max_turns: int = 5          # ConvPlanner 最大对话轮次
    temperature: float = 0.2

@dataclass
class LogConfig:
    base_dir: str = ".react/plan/logs"
    max_size_mb: float = 10.0
    rotate: bool = True
```

---

## 快速开始

```python
from plan import PlanOrchestrator, OrchestratorConfig
from plan.planner import PlannerAgent
from plan.replanner import ReplannerAgent
from plan.executor import ExecutorAgent

orchestrator = PlanOrchestrator(
    planner=PlannerAgent(llm=llm),
    replanner=ReplannerAgent(llm=llm),
    executor=ExecutorAgent(crew_cfg=crew_cfg),
    cfg=OrchestratorConfig(parallel_limit=4),
)

result = await orchestrator.run("分析竞品市场并生成报告")
print(result.answer)
```

或通过 TaoLoop 工具调用（需 `TaoConfig.plan` 非 `None`）：

```
[工具调用] run_plan(question="分析竞品市场并生成报告")
```
