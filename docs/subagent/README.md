# delegate / subagent 模块

按需委派子智能体的编排层，与 `scheduler/`（时钟触发）并列，负责主 Agent 在运行时动态派发子 Agent 执行具体任务。

> **重命名说明**：原 `subagent/` 模块已重命名为 `delegate/`，职责名称更清晰。`subagent/` 目录保留为向后兼容 shim，所有旧名称（`SubAgentManager`、`SubAgentConfig`、`SubAgentResult` 等）仍可正常导入，底层转发至 `delegate/` 的实现。
>
> **与 `crew/` 的关系**：当前 `TaoLoop` 使用 `crew/` 模块（`CrewManager` + `CrewConfig`）作为子 Agent 编排的实际实现。`delegate/` 模块与 `crew/` 同构，可作为独立模块或替换实现使用；两者 API 接口基本一致，主要差异在于 `CrewProfile` 额外支持 `recursive` 和 `return_log` 字段，且内置了 `planner` 预设。

---

## 架构定位

```
用户
  └─ 主 Agent（Orchestrator）
          │  分解任务，通过工具调用委派
          ▼
     DelegateManager          （src/delegate/manager.py）
          │
          ├─ delegate → 同步子 TaoLoop（当前线程）
          ├─ spawn    → 异步子 TaoLoop（后台线程）
          └─ spawn_all → 多个异步子 TaoLoop（并行线程）
```

主 Agent 的每一步 ReAct 推理本身即为编排图的执行节点；子 Agent 的工具集和角色由 `DelegateProfile` 约束，**子 Agent 的 `TaoConfig` 中 `delegate=None`、`scheduler=None`，禁止递归嵌套。**

> **Plan 模式**：若需更复杂的多智能体规划（含 DAG 调度、Replanner、人类编辑通道、资源锁等），请参阅 `src/plan/` 模块与 [plan/README.md](../plan/README.md)（如已创建）。

---

## 目录结构

```
src/delegate/
├── __init__.py    # 导出 DelegateConfig / DelegateProfile / DelegateManager / DelegateResult
├── config.py      # DelegateConfig + DelegateProfile + _default_profiles()
├── result.py      # DelegateResult dataclass
├── runner.py      # DelegateRunner.run_sync() — 线程内同步运行子 TaoLoop
└── manager.py     # DelegateManager — 所有编排原语

src/subagent/      # 向后兼容 shim（重导出 delegate/ 的类）
├── __init__.py    # SubAgentConfig = DelegateConfig, SubAgentManager = DelegateManager, ...
├── config.py
├── result.py
├── runner.py
└── manager.py
```

---

## 核心数据结构

### `DelegateProfile`（`SubAgentProfile` 为别名）

```python
@dataclass
class DelegateProfile:
    max_steps: int = 10
    memory: MemoryConfig = ...
    tools: list[str] | None = None   # None = 继承全工具集；或指定子集
    system_note: str = ""            # 附加到子 Agent 系统提示的角色描述
```

### `DelegateConfig`（`SubAgentConfig` 为别名）

```python
@dataclass
class DelegateConfig:
    llm_cfg_path: str = "config/llm_core/config.yaml"
    profiles: dict[str, DelegateProfile] = ...   # 懒加载，默认含三个预置 profile
    max_concurrent: int = 4
```

### `DelegateResult`（`SubAgentResult` 为别名）

```python
@dataclass
class DelegateResult:
    agent_id: str
    status: str    # "running" | "done" | "failed" | "not_found" | "timeout"
    answer: str = ""
    error: str = ""
```

---

## 内置 Profile 预设

| profile | tools 限定 | system_note |
|---|---|---|
| `minimal` | 全工具集（None） | 无 |
| `researcher` | web_search + web_fetch + knowledge_hybrid_search + knowledge_save + knowledge_list | 信息研究与知识整理专家 |
| `analyst` | calculator + unit_converter + web_search + get_datetime + word_count | 数据分析与计算推理专家 |

可在 `DelegateConfig.profiles` 中自定义任意数量的 profile。

---

## `DelegateManager` 接口

```python
manager = DelegateManager(cfg: DelegateConfig)

# 同步委派：阻塞当前线程，适合需要即时结果的短时任务
answer: str = manager.delegate(instruction, profile="minimal")

# 异步派发：立即返回，子 Agent 在后台线程运行
agent_id: str = manager.spawn(instruction, profile="minimal")

# 批量并行 Fan-out：同时派发多个子 Agent
agent_ids: list[str] = manager.spawn_all([
    {"instruction": "...", "profile": "researcher"},
    {"instruction": "...", "profile": "analyst"},
])

# 非阻塞查询
result: DelegateResult = manager.get_result(agent_id)

# 阻塞等待单个完成（含超时）
result: DelegateResult = manager.await_agent(agent_id, timeout=300.0)

# Fan-in 收集：等待所有完成并返回结果列表
results: list[DelegateResult] = manager.await_all(agent_ids, timeout=300.0)
```

---

## 工具层（`react/action/tools/impl/`）

主 Agent 通过以下工具调用 `DelegateManager`：

| 工具名 | 对应方法 | 典型场景 |
|---|---|---|
| `delegate_task` | `manager.delegate()` | 简单一次性委派，需要立即结果 |
| `spawn_agent` | `manager.spawn()` | 长时任务，主 Agent 可继续推理 |
| `get_agent_result` | `manager.get_result()` | 轮询异步子 Agent 状态 |
| `spawn_all` | `manager.spawn_all()` | 并行分解大任务（Fan-out） |
| `await_agent` | `manager.await_agent()` | 在某一步明确等待子 Agent 完成 |
| `await_all` | `manager.await_all()` | 收集所有并行结果（Fan-in） |

---

## 编排模式示例

### 顺序委派（最简单）

```
主 Agent 步骤 1: delegate_task("搜索关于量子计算的最新进展", profile="researcher")
              → 子 Agent 运行完毕，返回研究结果
主 Agent 步骤 2: 基于结果撰写摘要，直接回答用户
```

### 并行 Fan-out + Fan-in

```
主 Agent 步骤 1: spawn_all([
                  {"instruction": "研究主题A", "profile": "researcher"},
                  {"instruction": "分析数据集B", "profile": "analyst"},
                  {"instruction": "搜索竞品C", "profile": "researcher"},
                ])
              → 返回 [agent_id_A, agent_id_B, agent_id_C]

主 Agent 步骤 2: await_all([agent_id_A, agent_id_B, agent_id_C])
              → 三个子 Agent 全部完成，返回结果列表

主 Agent 步骤 3: 综合三份结果，生成最终答案
```

### 异步查询（适合超长任务）

```
主 Agent 步骤 1: spawn_agent("执行耗时分析...", profile="analyst")
              → agent_id = "abc-123"，继续其他推理

主 Agent 步骤 N: get_agent_result("abc-123")
              → status="running"，继续等待

主 Agent 步骤 N+k: get_agent_result("abc-123")
              → status="done"，获取 answer
```

---

## 与 `scheduler/` 和 `plan/` 的区别

| | scheduler | delegate | plan |
|---|---|---|---|
| 触发方式 | 时钟（到达指定时间）| 主 Agent 主动调用 | 编排器自动按 DAG 依赖 |
| 结果消费 | 写入 `results/*.json` | 主 Agent 在当前会话内读回 | PlanOrchestrator 汇总 |
| 状态持久化 | `tasks.json`（跨重启）| 内存字典（进程内有效）| 快照（`.react/plan/snapshots/`）|
| 计划语言 | — | — | Markdown → PlanDocument IR |
| 适用场景 | 定时报告、周期监控 | 任务分解、并行计算、角色委派 | 复杂多步骤目标、需要 Replanner |
