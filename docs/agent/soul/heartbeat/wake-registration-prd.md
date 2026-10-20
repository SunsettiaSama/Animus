# PRD：心跳注册契约（wake registration）

> 版本 v1 · 2026-09-22 · 状态：已批准实施
> 目标有且只有一个：**让 agent 的心脏跳动起来。**

## 0. 语义边界

heartbeat 是 **agent 自身的调度心脏**，只做三件事：

1. **到期判定**（interval / daily / monthly）；
2. **按注册契约调用** target；
3. **异常隔离与记录**（worker 兜异常、失败计数、vitals）。

不包含更高层调度（scheduler engine 的任务预约、跨 agent 编排不进心跳线）；
不包含任何模块的业务实现——**persona 的人格漂移实现写在 persona，wander 胶水
写在 memory，story tick 写在 wiring/story**。heartbeat 零模块知识。

## 1. 注册契约

`ChecklistItem` 显式携带调用目标（不再靠 domain/action 隐式路由）：

```python
ChecklistItem(
    id="memory-wander",
    domain="memory", action="wander",          # 仅标识/日志，不用于路由
    trigger=ChecklistTrigger.interval,
    interval_sec=cfg.wander_interval_sec,
    target="agent.soul.memory.heartbeat:run_wander_entry",  # 调用包名称
    heavy=True,                                # 重任务入 SoulEvolutionWorker
    run_outside_active_hours=False,            # 活跃时段外仍执行（memory-sleep）
    avoid_when_speaking=False,                 # 说话中避让（声明式策略）
    payload={...},
)
```

**target 三种形态**（`schedule/resolve.py` 统一解析，每次调用时懒解析）：

| 形态 | 示例 | 解析 |
|---|---|---|
| 包名字符串（契约首选） | `"agent.soul.memory.heartbeat:run_wander_entry"` | `importlib` 导入模块取属性 |
| soul 入口字符串 | `"soul:run_presence_wake"` | 在 `ctx.soul` 上逐级 getattr |
| 可调用对象 | `lambda payload, ctx: ...` | 直接调用（wiring 特例） |

**调用契约**：`target(payload: dict, ctx: HeartbeatContext) -> Any`，返回值进
`ChecklistRunResult.detail`。`HeartbeatContext(soul, scheduler_engine,
vitals_provider)` 由 orchestrator 每次调用时构造；实现方在注册项里闭包或经
ctx 获取依赖。

**注册 API**：`ChecklistRegistry.register(item)` / `register_all(items)`，
同 id 后者覆盖前者并告警；注册时校验 target 非空。

## 2. 实现归位（迁移映射，行为保持）

| 原心跳内特化处理器 | 新家 |
|---|---|
| `_run_wander`（wander + 演化捕获 + 塑形） | `soul/memory/heartbeat.py` |
| `_run_memory_sleep` + `memory_sleep_at` 解析 | `soul/memory/heartbeat.py` |
| memory-forget（原通用 dispatch） | `soul/memory/heartbeat.py` |
| `_run_plan_landmark`（life_worker + 捕获 + 剧情 beat） | `soul/life/heartbeat.py` |
| `_run_trigger_landmarks` / `_run_tick_surprise` | `soul/life/heartbeat.py` |
| scheduler digest（最近任务格式化 + dispatch） | `soul/life/heartbeat.py` |
| `_run_scan_expectation` / `_run_scan_external` / `_run_presence_wake` | `soul/presence/heartbeat.py` |
| persona-monthly-drift（原通用 dispatch） | `soul/persona/heartbeat.py` |
| story-tick | `soul/wiring/story_tick.py` |

依赖方向修正：`evolution_capture.py` 上移至 `src/agent/soul/evolution_capture.py`
（域入口要用它，域包不得反向 import 心跳 L5）。`default_checklist()` 从心跳
删除；等价项由各域 `wake_items(cfg)` 提供，id/间隔/行为与迁移前逐一一致
（12 项：life×4、story×1、memory×3、presence×3、persona×1）。

## 3. 装配

`soul/wiring/heartbeat.py::register_default_wake_items(module, soul)`：
汇集五域 wake_items 注册进 checklist；`SoulService._ensure_heartbeat()` 与
`bind_heartbeat()` 在 checklist 为空时调用（不覆盖外部自带项）。
`HeartbeatModule` 默认持空 checklist。`module.tick` 的 memory-sleep 硬编码
id 改为按 `run_outside_active_hours` 标志查询。

## 4. 非目标

- 不接每日 planner/review、story 演化线程收编、注入信箱消费（后续接入批次）；
- 不新增 schedule_once / 亚分钟原语；
- module.tick 的活跃时段强制醒睡门控保留在 runtime 层（agent 级语义）。

## 5. 验收

- 真 SoulService 启动后 tick 一次，12 个默认项全部经注册契约执行；
- heartbeat 包内 grep 不到 `run_wander|plan_landmark|story_tick|presence_wake|monthly_drift` 等业务知识；
- 回归绿：heartbeat 全套 + 感知 + speak 队列子集。
