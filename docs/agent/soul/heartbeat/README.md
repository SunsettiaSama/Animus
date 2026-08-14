# agent/soul/heartbeat

Soul heartbeat 是由 `SoulService` 自行启动的周期演化系统。它拥有独立线程和 checklist，不由 `runtime.scheduler.SchedulerEngine` 定时驱动。

## 当前结构

```text
src/agent/soul/heartbeat/
├── core_service.py       HeartbeatCoreService：周期线程、注入窗口、邮箱
├── module.py             HeartbeatModule：活跃时段、wake/sleep、tick
├── orchestrator.py       到期 checklist 的同步执行/重任务入队
├── checklist/            ChecklistRegistry 与默认项目
├── worker.py             SoulEvolutionWorker
├── bridge.py             MemoryHeartbeatResult → Presence
├── evolution.py          wander 辅助
├── evolution_capture.py  演化结果捕获
├── inject_mailbox.py     下一轮会话注入邮箱
├── tick_log.py           tick 本地日志
├── task_runner.py        Scheduler task executor 适配
└── config.py             SoulHeartbeatConfig
```

源码中没有 `checker.py`、`HeartbeatChecker` 或读取 `HEARTBEAT.md` 的 precheck 流程。

## 运行关系

```text
SoulService.start()
  ├── HeartbeatModule.start_evolution_worker()
  └── HeartbeatCoreService.start()
        └── daemon thread（poll_interval_sec）
              ├── 刷新延迟注入
              ├── 可选 preflight_instruction
              └── HeartbeatModule.tick()
                    ├── active hours 外：Presence sleep，tick skip
                    ├── active hours 内：Presence wake
                    └── HeartbeatOrchestrator.run_due()
```

`HeartbeatCoreService` 把非空 `HeartbeatTickResult.detail_for_inject` 放入 `HeartbeatInjectMailbox`。`inject_window_mode=user` 直接按窗口投递；`agent` 模式会用辅助 LLM 判定 `INJECT/DEFER`。

当前 checklist tick 通常只填写 outcome/reason，未必产生 `detail_for_inject`；因此“心跳一定向下一轮对话注入摘要”不是可保证能力。

## checklist 与重任务

轻量项目直接调用 `SoulService`，重项目进入 `SoulEvolutionWorker`。当前重任务键包括：

- Memory：wander、forget scan、sleep
- Life：plan landmark
- Persona：monthly drift

其它项目包括 landmark trigger、surprise、Presence expectation/external scan、wake/sleep 等。Memory wander 的情绪信号会经 `heartbeat/bridge.py` 写入 Presence。

## 与 Scheduler 的边界

Heartbeat 主循环、活跃时段和 checklist 均不要求 Scheduler。

仍存在两处可选关联：

1. `HeartbeatOrchestrator._format_recent_tasks()` 在已注入 scheduler engine 时读取最近完成任务，供 Life scheduler digest 使用。
2. 配置了 `preflight_instruction` 时，`HeartbeatCoreService` 会要求 scheduler engine，并通过 `SubAgentRunner` 执行一次 preflight。

第二项是显式配置才启用的附加能力；没有 scheduler engine 时会跳过，不影响 heartbeat tick。它不是 `HEARTBEAT.md` checker，也不是每个 checklist 项之前的 precheck。

`task_runner.py` 是运行时 Scheduler 的执行器适配，不代表 Scheduler 驱动 Soul heartbeat。

## 生命周期与接入状态

- `SoulService.start()` 总会确保 `HeartbeatModule`、evolution worker 与 core thread 启动。
- `SoulService.stop()` 停止 core thread和 evolution worker。
- `bind_scheduler_engine()` 可选；未绑定时 heartbeat 仍运行。
- 邮箱只有被会话层消费时才会进入 prompt；仅启动 core service 不等于用户可见。
