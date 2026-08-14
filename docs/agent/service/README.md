# agent/service — AgentService

`AgentService` 是调度器宿主，不是 WebUI 的主对话运行时。实现位于 `src/agent/service.py`。

## 职责

- 构造并持有 `TaskRunner`。
- 在 `start()` 中构造 `SchedulerEngine`，启动其 `TemporalClock`。
- 提供 `run_once()`，通过 `SubAgentRunner` 执行一次性指令。
- 在注入 `SoulService` 时管理其生命周期，并把已创建的 scheduler engine 绑定给 Soul，供 Soul 的编排逻辑访问。

当前启动链如下：

```text
AgentService.__init__()
  └─ TaskRunner(engine=None)

AgentService.start()
  ├─ SchedulerEngine(cfg, executor=task_runner, heartbeat=None)
  ├─ task_runner._engine = engine
  ├─ engine.start()
  └─ SoulService.start()（如尚未运行）
       └─ SoulService.bind_scheduler_engine(engine)
```

`SchedulerEngine` 的 `heartbeat` 明确传入 `None`。Soul 心跳不由调度时钟触发：`SoulService` 自行创建 `HeartbeatModule`，并由独立的 `HeartbeatCoreService` daemon 线程驱动。`AgentService.force_heartbeat()` 也是转发到 `SoulService.force_heartbeat_tick()`。

## 任务结果链

`TaskRunner` 可接收 `long_term`、`timeline`、`journal`、`channel_router` 与 `notify_fn`。任务完成后可写入调度结果文件、时间线和工作日志，再按 delivery 配置通知目标。`life_manager`、`persona_manager`、`memory_service` 和 `llm_service` 虽仍出现在构造参数中，但当前 `AgentService` 不直接使用它们。

## 生命周期约束

- 初始状态为 `idle`；只有 `idle` 可 `start()`。
- `stop()` 先停止运行中的 Soul，再停止 scheduler clock，状态变为 `stopped`。
- 当前实例停止后不能再次启动；再次调用会被状态检查忽略。
- `engine` 在 `start()` 前为 `None`。

## 相关文档

- [runtime/README.md](../../runtime/README.md)
- [agent/soul/heartbeat/README.md](../soul/heartbeat/README.md)
