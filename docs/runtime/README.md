# runtime / scheduler

**运行时调度层**：任务持久化、独立时钟线程、以及与 Agent 层解耦的 **`HeartbeatProtocol`** / **`TaskExecutorProtocol`**。实现位于 **`src/runtime/scheduler/`**，不含对 `agent.*` 的硬依赖（具体执行器与心跳由 Soul 侧注入）。

---

## 目录结构

```
src/runtime/scheduler/
├── engine.py           # SchedulerEngine — 门面 API（schedule_once / cron / cancel / list_timeline）
├── clock.py            # TemporalClock — daemon 线程驱动触发
├── store.py            # TaskStore — JSON 持久化任务状态
├── task.py             # ScheduledTask、Trigger、TaskStatus、DeliveryMode
├── config.py           # SchedulerConfig（含 heartbeat: HeartbeatConfig）
├── heartbeat_config.py # HeartbeatConfig
├── heartbeat_iface.py  # HeartbeatProtocol（TemporalClock 仅依赖此协议）
├── executor.py         # TaskExecutorProtocol
├── timeline.py / timeline_service.py
├── event_bus.py / journal.py / shadow.py / command.py
└── ...
```

---

## SchedulerEngine

- 构造：`SchedulerEngine(cfg, executor, heartbeat=None, timeline=None, notify_fn=None, …)`。
- **`executor`**：`agent.soul.heartbeat.task_runner.TaskRunner`（或其它实现协议的类型）。
- **`heartbeat`**：`agent.soul.heartbeat.module.HeartbeatModule`（实现 `HeartbeatProtocol`）。
- **`start()` / `stop()`**：启动或停止内部 **`TemporalClock`** 线程（与 uvicorn asyncio 隔离）。

---

## SchedulerConfig

- **`scheduler_dir`**：默认 `.react/scheduler/`（任务库、结果、`HEARTBEAT.md` 等路径锚点）。
- **`heartbeat`**：`HeartbeatConfig`（清单路径、活跃时段、核心心跳线程开关等）。
- **`profiles`**：任务使用的 `SubAgentProfile` 名称映射；默认值由 **`agent.soul.heartbeat.profiles.make_default_scheduler_config()`** 注入。

---

## TaoLoop 集成

当 **`TaoConfig.scheduler`** 非空且未注入全局 engine 时，`TaoLoop` 可就地构造 **`SchedulerEngine`** 并注册 `scheduler_add` / `scheduler_list` / `scheduler_cancel` 等工具（见 `agent/react/action/tools/impl/`）。

---

## 相关文档

- [agent/soul/heartbeat/README.md](../agent/soul/heartbeat/README.md)
- [agent/service/README.md](../agent/service/README.md)
- [storage/README.md](../storage/README.md) — `.react/scheduler/` 布局
