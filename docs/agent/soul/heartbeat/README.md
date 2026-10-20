# agent/soul/heartbeat

Soul heartbeat 是由 `SoulService` 自行启动的周期演化系统，也是**唤起线**：
任何需要长时间预约/周期唤醒 LLM 的工作都走这条线。它拥有独立线程和 checklist，
不由 `runtime.scheduler.SchedulerEngine` 定时驱动。

线体铁律：任何组件故障不允许线程死亡或静默（救线日志直写 logger.exception，
不受 console_log_enabled 门控）。

## 抽象层级（依赖只准向下）

```text
src/agent/soul/heartbeat/
├── probe/         L1 读事实 — soul 各部位只读采样，绝不抛异常
│   ├── base.py             SoulProbe / ProbeReading（缺失或异常 → unknown）
│   ├── speak_probe.py      speaking / typing（SpeakService.any_busy/any_typing 聚合口）
│   ├── presence_probe.py   awake
│   ├── worker_probe.py     evolving（演化 worker 队列/线程）
│   └── self_probe.py       心跳自身（失败计数/线程存活/信箱积压）
├── vitals/        L2 折叠变量 — 探针读数 → SoulVitals 状态快照
│   └── snapshot.py         SoulVitals / VitalsBuilder（unknown_parts 诚实标注）
├── policy/        L3 变量→决策 — 纯函数，vitals=None 时放行
│   ├── inject_policy.py    speaking → 注入避让（防串台）
│   ├── sleep_policy.py     speaking → 入睡避让（唤醒不受限）
│   └── liveness_policy.py  ok / degraded / failing 存活判定
├── schedule/      L4 时间→到期 — 注册表 + 到期判定 + 目标解析
│   ├── item.py             ChecklistItem（wake 契约载体：target/heavy/避让标志）
│   ├── registry.py         ChecklistRegistry（register/register_all 动态注册）
│   ├── context.py          HeartbeatContext（target 调用环境：soul/engine/vitals）
│   ├── resolve.py          target 解析（"包.模块:函数" / "soul:方法" / callable）
│   ├── landmark_schedule.py
│   ├── task_runner.py      Scheduler task executor 适配
│   └── profiles.py         默认调度 profile 构造
├── orchestrate/   L5 执行 — 到期项编排
│   ├── orchestrator.py     通用执行：解析 target → 调用；heavy 分流；submit_heavy；避让策略
│   └── worker.py           SoulEvolutionWorker（soul-evolution 线程）
└── runtime/       L6 线程与装配
    ├── core_service.py     heartbeat-core 主循环（兜异常/判定超时/注入窗口）
    └── module.py           总装：vitals builder、活跃时段、tick

根叶（横切）：config / window（跨零点窗口，fail-open）/ console_log /
tick_log（单代轮转 + 坏行容错）/ inject_mailbox（单槽，peek 非破坏读）。
bridge.py 是契约叶子：memory/life/presence 在 import 期引用，**位置不可动**
（防环约束见 `__init__.py` docstring）。
```

## 注册契约（wake registration，见 wake-registration-prd.md）

heartbeat 是 **agent 自身的调度心脏**，零模块知识：实现住在各域的
`heartbeat.py` 入口（memory/life/presence/persona + wiring/story_tick），
由 `soul/wiring/heartbeat.py` 汇集注册（`SoulService._ensure_heartbeat`
与 `bind_heartbeat` 在 checklist 为空时调用，不覆盖外部自带项）。

```python
ChecklistItem(
    id="memory-wander", domain="memory", action="wander",   # domain/action 仅标识
    trigger=interval, interval_sec=cfg.wander_interval_sec,
    target="agent.soul.memory.heartbeat:run_wander_entry",  # 调用包名称
    heavy=True,                          # 重任务入 SoulEvolutionWorker
    run_outside_active_hours=False,      # 活跃时段外仍执行（memory-sleep 语义）
    avoid_when_speaking=False,           # soul 说话中避让（声明式策略）
)
```

target 契约：`target(payload: dict, ctx: HeartbeatContext) -> Any`；
三种形态——包名字符串 `"包.模块:函数"`（首选）、soul 入口 `"soul:方法"`、
可调用对象。不包含高层调度（scheduler 任务预约、跨 agent 编排不进心跳线）。

## 生命体征（vitals）

`HeartbeatModule.vitals()` 每次调用现采一次 `SoulVitals`：

| 变量 | 语义 | 来源探针 |
|---|---|---|
| `speaking` | 任一会话 turn/推送进行中 | speak |
| `typing` | 任一会话用户打字中 | speak |
| `awake` | presence 清醒 | presence |
| `evolving` | 演化 worker 有任务 | evolution_worker |
| `heartbeat_failures` | 主循环连续失败 | heartbeat |
| `thread_alive` | 心跳线程存活 | heartbeat |
| `inject_pending` | 信箱或暂存有待注入 | heartbeat |
| `unknown_parts` | 读不到的部位（如实标注） | — |

行为接线（policy 消费 vitals）：

- 注入避让：`core_service._iteration` 在注入前问 `should_offer_inject`，
  speaking 时文本进 `_deferred` 下轮重试；
- 入睡避让：`module.tick` 活跃时段外的强制入睡与 checklist 的
  presence-sleep 项都先过 `may_sleep`，speaking 时推迟；唤醒不受限；
- 存活暴露：`SoulService.status()["workers"]["heartbeat_vitals"]` 含
  vitals 快照与 `judge_liveness` 判定（ok/degraded/failing）。

本轮边界：只判定与避让，不做自动拉起/重启类自愈。

## 运行关系

```text
SoulService.start()
  ├── HeartbeatModule.start_evolution_worker()
  └── HeartbeatCoreService.start()
        └── daemon thread（poll_interval_sec，默认 300s）
              ├── 刷新延迟注入（_flush_deferred_if_due）
              ├── 可选 preflight_instruction
              └── HeartbeatModule.tick()
                    ├── active hours 外：Presence sleep（speaking 时避让），tick skip
                    ├── active hours 内：Presence wake
                    └── HeartbeatOrchestrator.run_due()
                          ├── 轻量项 → SoulService.dispatch（同步）
                          └── 重项 → SoulEvolutionWorker（soul-evolution 线程）
```

重任务（`item.heavy=True`）入 SoulEvolutionWorker：memory 的 wander /
forget / sleep、life 的 plan landmark、persona 的 monthly drift、story 的
演化过道（`story-evolve`，由 tick 经 `submit_heavy` 派生）。
`runtime/scheduler/heartbeat.py` 的 ensure 项每小时幂等确保每日 planner
（08:00）/review（22:00）cron 注册在 engine 时间轴上（执行由 engine 时钟负责）。
旧线路迁移记录见 legacy-lines-migration.md。

`HeartbeatCoreService` 把非空 `detail_for_inject` 经注入窗口/agent 判定/
speaking 避让后放入 `HeartbeatInjectMailbox`。注意：mailbox 当前生产侧
**只写不读**（`take_for_prompt` 无调用方），注入消费点接入 speak 管线是
待拍板的后续工作；`peek/has_pending` 已备好只读口。

## 与 Scheduler 的边界

Heartbeat 主循环、活跃时段和 checklist 均不要求 Scheduler。两处可选关联：
`_format_recent_tasks()` 读 scheduler 最近任务（life digest 用）；
配置 `preflight_instruction` 时经 `SubAgentRunner` 跑一次 preflight。
`task_runner.py` 是 Scheduler 的执行器适配，不代表 Scheduler 驱动 heartbeat。

## 生命周期与接入状态

- `SoulService.start()` 总会确保 HeartbeatModule、evolution worker、core thread
  启动；core 启动后经 `attach_core_service` 回填自身探针。
- `SoulService.stop()` 停止 core thread 与 evolution worker（join 超时会告警）。
- `bind_scheduler_engine()` 可选；未绑定时 heartbeat 仍运行。
- 测试：`src/test/soul/test_heartbeat_survival.py`（存活/窗口/轮转/判定超时，
  秒级假件）、`test_heartbeat_vitals.py`（探针/折叠/策略/接线）、
  `test_heartbeat_integration.py`（真 SoulService 集成）。
