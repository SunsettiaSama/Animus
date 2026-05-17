# agent/soul/heartbeat

Soul 侧 **主动心跳**：周期性读取调度目录下的清单文件（默认 `HEARTBEAT.md`），经 LLM `precheck` 判断是否需要介入（如 `ESCALATE` → 子 Agent），并与 **`runtime.scheduler.SchedulerEngine`** 通过 `HeartbeatProtocol` 对接。持久化服务组装见 **`agent/service.py`** 中的 `AgentService`。

---

## 目录结构

```
src/agent/soul/heartbeat/
├── module.py           # HeartbeatModule — tick()、活跃时段、与 LifeManager 钩子
├── checker.py          # HeartbeatChecker — LLM precheck / escalate → SubAgentRunner
├── task_runner.py      # TaskRunner — TaskExecutorProtocol，执行调度任务写 results/
├── profiles.py         # make_default_scheduler_config() — 默认 SchedulerConfig + profiles
├── core_service.py     # HeartbeatCoreService — 可选常驻线程；注入窗口与邮箱
├── inject_mailbox.py   # HeartbeatInjectMailbox — ConvLoop 侧读取待注入摘要
└── tick_log.py         # HeartbeatTickLog / HeartbeatTickResult — heartbeat_log.jsonl
```

---

## 核心流程

1. **`TemporalClock`**（runtime）按配置触发 `heartbeat.tick()`（若启用且协议非空）。
2. **`HeartbeatModule.tick()`**：活跃时段外直接 skip；读取 `HeartbeatConfig.heartbeat_file` 内容；可选 `_run_life_hooks`（日终回顾、活动日志）；调用 **`HeartbeatChecker.precheck(content)`**。
3. **Precheck**：返回 `HEARTBEAT_OK` 或 `ESCALATE: …`；后者受每日 escalation 预算约束。
4. **Escalate**：`HeartbeatChecker.run_escalate` 构造 `SubAgentRunner` 执行临时推理。
5. **`HeartbeatCoreService`**（可选，`core_service_enabled`）：独立线程轮询 `tick()`，将摘要写入 **`HeartbeatInjectMailbox`**，供用户在注入窗口内并入下一轮对话上下文。

---

## 配置入口

- **`HeartbeatConfig`**：`runtime/scheduler/heartbeat_config.py`，嵌套在 **`SchedulerConfig.heartbeat`**（`runtime/scheduler/config.py`）。
- 关键字段：`heartbeat_file`、`active_hours_*`、`max_escalations_per_day`、`core_service_enabled`、`inject_window_*`、`clock_drives_heartbeat` 等。

---

## 与调度运行时关系

| 组件 | 包路径 | 职责 |
|---|---|---|
| `SchedulerEngine` | `runtime.scheduler.engine` | 门面：`TaskStore` + `TemporalClock` |
| `TaskRunner` | `agent.soul.heartbeat.task_runner` | 执行到点的任务（异步 `run`） |
| `HeartbeatModule` | `agent.soul.heartbeat.module` | 心跳清单与 escalate |
| `AgentService` | `agent.service` | `start()` 时创建 Engine 并回注依赖 |

引擎层 **不 import agent**；心跳与执行器通过 **`HeartbeatProtocol`** / **`TaskExecutorProtocol`** 注入。

---

## 相关文档

- [runtime 调度器](../../../runtime/README.md)
- [agent/service](../../service/README.md)
- [agent/soul/life](../life/README.md)（心跳钩子调用 `LifeManager`）
