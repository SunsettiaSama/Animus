# runtime / scheduler

`src/runtime/scheduler/` 是与 Agent 实现解耦的任务调度层：持久化任务、轮询到期任务，并通过注入的 `TaskExecutorProtocol` 执行。生产 WebUI 中的宿主是 `AgentService`。

## 主要模块

```text
src/runtime/scheduler/
├── engine.py            SchedulerEngine 门面
├── clock.py             TemporalClock 独立 daemon 线程与 asyncio loop
├── store.py             TaskStore（tasks.json）
├── task.py              ScheduledTask / Trigger / TaskStatus / DeliveryMode
├── config.py            SchedulerConfig
├── executor.py          TaskExecutorProtocol
├── heartbeat_iface.py   可选的旧 heartbeat 协议
├── heartbeat_config.py  旧 clock heartbeat hook 的配置
├── timeline.py          按日 JSONL 的 TimelineStore
├── timeline_service.py  TimelineService 门面
├── journal.py           写入 history 的 WorkJournal
└── event*.py / shadow.py / command.py
```

## SchedulerEngine 与 TemporalClock

构造签名为：

```python
SchedulerEngine(cfg, executor, heartbeat=None, timeline=None,
                notify_fn=None, journal=None, channel_router=None)
```

当前 `AgentService.start()` 始终使用 `heartbeat=None`。因此 `TemporalClock` 只负责：

1. 启动时把遗留的 `running` 任务恢复为 `pending`；
2. 按 `poll_interval` 查找到期任务，并在 `max_concurrent` 限制内调用 `executor.run()`；
3. 每日清理超过 `task_retention_days` 的终态任务。

`TemporalClock` 仍保留可选 `HeartbeatProtocol` 分支，但这是旧扩展点，不是当前 Soul 心跳链。Soul 的 `HeartbeatModule` 由 `SoulService` 持有，`HeartbeatCoreService` 独立驱动。

## 调度 API

`SchedulerEngine` 当前提供：

- `schedule_once()`、`schedule_interval()`、`schedule_cron()`
- `cancel()`、`pause()`、`resume()`、`get()`、`list_timeline()`
- `pause_clock()`、`resume_clock()`
- `schedule_daily_planner()`、`schedule_daily_review()`

`list_timeline()` 返回的是 `TaskStore` 中的任务列表；事件时间线由独立的 `TimelineService.read()` / `append()` 管理。

## 配置与持久化

`SchedulerConfig.scheduler_dir` 默认是 `.react/scheduler`，其中 `TaskStore` 创建 `tasks.json` 和 `results/`。`profiles` 默认空，由 Agent 层的 `make_default_scheduler_config()` 注入 `SubAgentProfile`。

`SchedulerConfig.heartbeat` 只配置上述可选旧 hook；它不代表 Soul 心跳已接入 scheduler。

## AppState 启动装配

WebUI 的装配入口在 `src/webui/state.py` 和 `src/webui/app.py`：

1. `get_state()` 首次调用创建 `AppState`。
2. `AppState.__post_init__()` 解析项目路径，并装配 `BackgroundTaskRunner`、`LLMService`、三个本地推理 manager、sandbox、service registry、工具与 bot 服务。
3. WebUI startup 把后续工作提交到后台：加载 LLM 配置并启动 `LLMService`。
4. `do_soul_init()` 创建并启动作为主运行时的 `SoulService`；Speak 与 Soul heartbeat 在此链中就绪。
5. 装配 Worker state。
6. 最后创建并启动 `AgentService`，再把 `agent_service.engine` 保存到 `state.scheduler_engine`。

因此 scheduler 是 Soul/Speak 启动后的宿主服务，不是 WebUI 对话的初始化入口。shutdown 优先停止 `AgentService`；它会连同 Soul 和 scheduler clock 一起停止。

旧 `TaoLoop` 在注入全局 engine 时注册 `scheduler_add`、`scheduler_list`、`scheduler_cancel`；未注入且配置了 scheduler 时仍可创建 loop 私有 engine。WebUI factory 优先使用 `AppState.scheduler_engine`。

## 相关文档

- [agent/soul/heartbeat/README.md](../agent/soul/heartbeat/README.md)
- [agent/service/README.md](../agent/service/README.md)
- [storage/README.md](../storage/README.md)
