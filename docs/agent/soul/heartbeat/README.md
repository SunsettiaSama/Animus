# agent/soul/heartbeat

Soul 侧 **主动心跳**：周期性读取调度清单、驱动 Soul 各域演化 checklist，并与 **`runtime.scheduler.SchedulerEngine`** 通过协议对接。持久化服务组装见 **`agent/service.py`** 中的 `AgentService`。

---

## 目录结构

```
src/agent/soul/heartbeat/
├── module.py               # HeartbeatModule — tick()、活跃时段、Life 钩子
├── orchestrator.py         # HeartbeatOrchestrator — checklist 到期项 → dispatch
├── checklist/              # ChecklistRegistry / 调度项注册
├── checker.py              # HeartbeatChecker — LLM precheck / escalate
├── task_runner.py          # TaskRunner — TaskExecutorProtocol
├── worker.py               # SoulEvolutionWorker — 重任务异步队列
├── bridge.py               # memory tick → EmotionalSignal → presence
├── evolution.py            # wander 演化步骤
├── evolution_capture.py    # EvolutionCapture
├── profiles.py             # make_default_scheduler_config()
├── core_service.py         # HeartbeatCoreService — 注入窗口与邮箱
├── inject_mailbox.py       # HeartbeatInjectMailbox
└── tick_log.py             # HeartbeatTickLog
```

---

## 双轨心跳

### 1. HeartbeatModule（清单 precheck）

1. **`TemporalClock`** 触发 `heartbeat.tick()`。
2. **`HeartbeatModule.tick()`**：活跃时段外 skip；读取 `HEARTBEAT.md`；可选 Life 日终钩子；调用 **`HeartbeatChecker.precheck`**。
3. Precheck 返回 `HEARTBEAT_OK` 或 `ESCALATE` → `SubAgentRunner`。
4. **`HeartbeatCoreService`**（可选）：独立线程将摘要写入 **`HeartbeatInjectMailbox`**。

### 2. HeartbeatOrchestrator（Soul 演化 checklist）

`SoulService.bind_heartbeat()` 后可用：

```
HeartbeatOrchestrator.run_due()
    → 扫描 ChecklistRegistry 到期项
    → 轻量项：soul.dispatch(SoulRequest) 同步执行
    → 重项：SoulEvolutionWorker 异步（wander / forget_scan / plan_landmark / run_monthly_drift）
```

重项判定见 `orchestrator._HEAVY_ITEM_KEYS`。

典型 checklist 动作：memory wander、life landmark、persona drift、presence expectation scan、life surprise tick 等。

### memory → presence 桥

`bridge.py`：`MemoryHeartbeatResult` → `EmotionalSignal` → `PresenceService.receive_heartbeat_signal`。

---

## 配置入口

- **`HeartbeatConfig`**：`runtime/scheduler/heartbeat_config.py`，嵌套在 **`SchedulerConfig.heartbeat`**。
- **`SoulConfig`**：`config/soul/config.py` — checklist 间隔、presence wake 等 Soul 域参数。

---

## 与调度运行时关系

| 组件 | 包路径 | 职责 |
|---|---|---|
| `SchedulerEngine` | `runtime.scheduler.engine` | 门面：TaskStore + TemporalClock |
| `TaskRunner` | `agent.soul.heartbeat.task_runner` | 执行到点任务 |
| `HeartbeatModule` | `agent.soul.heartbeat.module` | 清单 precheck / escalate |
| `HeartbeatOrchestrator` | `agent.soul.heartbeat.orchestrator` | Soul 域 checklist 编排 |
| `AgentService` | `agent.service` | start() 时创建 Engine 并回注依赖 |

引擎层 **不 import agent**；心跳与执行器通过 **`HeartbeatProtocol`** / **`TaskExecutorProtocol`** 注入。

---

## 相关文档

- [runtime 调度器](../../../runtime/README.md)
- [agent/service](../../service/README.md)
- [life/README.md](../life/README.md)（landmark / wander 钩子）
- [presence/README.md](../presence/README.md)（wake / emotional signal）
- [agent/soul/README.md](../README.md)（SoulService.bind_heartbeat）
