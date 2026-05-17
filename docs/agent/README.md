# subagent / 子 Agent 委派

按需将任务委派给子智能体的编排机制，与 **`runtime.scheduler`**（时钟触发任务，`SchedulerEngine`）并列；后者具体的 **`HeartbeatModule` / `TaskRunner`** 实现在 **`agent/soul/heartbeat`**。

---

## 架构定位

```
主 Agent（TaoLoop）
  │  推理过程中调用工具
  ▼
DelegateTaskSkill          （agent/react/action/skill/delegate_task.py）
  │  同步阻塞执行
  ▼
SubAgentRunner             （agent/runner.py）
  │  构建独立 TaoLoop，运行完毕后返回 answer
  ▼
SubAgentProfile            （agent/profile.py）
     └─ 约束子 Agent 的工具集、步数上限、系统提示
```

主 Agent 通过 `delegate_task` 工具（Skill）同步委派任务，子 Agent 在同一线程内运行一个独立的 `TaoLoop`，完成后将 `answer` 返回给主 Agent 继续推理。**子 Agent 的 `TaoConfig` 中 `scheduler=None`，禁止递归嵌套。**

---

## Soul 子系统（索引）

持久记忆单元、心跳驱动的重构与归档、生命叙事等位于 `agent/soul/`，与推理环内的 React 记忆并行。详见 [agent/soul/README.md](./soul/README.md)，记忆模块详见 [agent/soul/memory/README.md](./soul/memory/README.md)。

---

## 目录结构

```
src/agent/
├── profile.py      # SubAgentConfig + SubAgentProfile + 内置 profile 预设
├── runner.py       # SubAgentRunner.run_sync() — 同步执行子 TaoLoop
├── soul/           # Soul 子系统（记忆 / 心跳 / 生命 / 人格，见 docs/agent/soul）
└── react/
    └── action/
        └── skill/
            └── delegate_task.py   # DelegateTaskSkill — 主 Agent 调用的委派工具
```

---

## 核心数据结构

### `SubAgentProfile`（`agent/profile.py`）

```python
@dataclass
class SubAgentProfile:
    max_steps: int = 10
    memory: MemoryConfig = ...        # 子 Agent 记忆配置（默认关闭中期/长期）
    tools: list[str] | None = None    # None = 继承全工具集；或指定允许的工具名列表
    system_note: str = ""             # 附加到子 Agent 系统提示的角色描述
```

### `SubAgentConfig`（`agent/profile.py`）

```python
@dataclass
class SubAgentConfig:
    llm_cfg_path: str = "config/llm_core/config.yaml"
    profiles: dict[str, SubAgentProfile] = ...   # 懒加载，默认含内置预设
    max_concurrent: int = 4
```

### 启用方式

在 `TaoConfig` 中设置 `agent` 字段：

```python
from config.agent.tao_config import TaoConfig
from agent.profile import SubAgentConfig

cfg = TaoConfig(
    agent=SubAgentConfig(
        llm_cfg_path="config/llm_core/config.yaml",
    )
)
```

`TaoLoop` 检测到 `cfg.agent is not None` 时，自动注入 `DelegateTaskSkill`，主 Agent 即可使用 `delegate_task` 工具。

---

## 内置 Profile 预设

| profile | tools 限定 | 说明 |
|---|---|---|
| `minimal` | 全工具集（None）| 通用，无角色限定 |
| `executor` | 全工具集（None）| 执行型，直接完成任务，不再委派 |
| `researcher` | web_search + web_fetch | 信息研究（知识库工具已移除）|
| `researcher_with_memory` | researcher 工具集 + memory_recall | 研究专家 + 长期记忆支持 |
| `analyst` | calculator + unit_converter + web_search + get_datetime + word_count | 数据分析与计算推理专家 |

可在 `SubAgentConfig.profiles` 中自定义任意数量的 profile。

---

## `DelegateTaskSkill` 工具接口

工具名：`delegate_task`

| 参数 | 类型 | 说明 |
|---|---|---|
| `instruction` | str | 交给子 Agent 执行的完整指令（必填）|
| `profile` | str | 子 Agent 能力配置，默认 `"minimal"` |

执行语义：**同步阻塞**，主 Agent 当前步骤等待子 TaoLoop 运行完毕，返回子 Agent 的 `answer` 字符串。

---

## `SubAgentRunner`

```python
class SubAgentRunner:
    def run_sync(
        self,
        instruction: str,
        profile: SubAgentProfile,
        llm_cfg_path: str,
        event_callback=None,    # 可选，转发子 Agent 事件（ChunkEvent/StepEvent/FinishEvent）
    ) -> dict:
        # 返回 {"answer": str, "step_count": int, "steps_log": list[str]}
```

`SubAgentRunner.run_sync` 构建独立的 `TaoLoop`（`scheduler=None`），运行完毕后返回结果字典。

---

## 编排示例

### 顺序委派

```
主 Agent 步骤 1: delegate_task(
                  instruction="搜索量子计算领域最新进展，整理成摘要",
                  profile="researcher"
                )
              → 子 Agent 运行完毕，返回研究结果
主 Agent 步骤 2: 基于结果撰写最终答案
```

### 配合调度器

`delegate_task` 本身为同步调用。若需要异步或定时执行子任务，请使用 **`SchedulerEngine`**（`scheduler_add` 工具，`TaoConfig.scheduler`）；若需要 DAG 编排，请直接阅读 **`src/agent/flow/`** 源码及下方 **`run_flow` / `flow_*`** 工具说明。

---

## 与调度器（`runtime.scheduler`）和 Flow 的区别

| | runtime.scheduler | subagent（delegate_task）| Flow（agent.flow）|
|---|---|---|---|
| 触发方式 | 时钟（到达指定时间）| 主 Agent 主动调用工具 | 编排器自动按 DAG 依赖 |
| 执行方式 | 异步后台线程 | 同步阻塞当前步骤 | 异步 DAG 调度 |
| 结果消费 | 写入 `results/*.json` | 主 Agent 在当前步骤立即读回 | FlowOrchestrator / 快照与日志汇总 |
| 适用场景 | 定时报告、周期监控 | 简单任务分解、角色委派 | 复杂多步骤目标、需要 Replanner |
