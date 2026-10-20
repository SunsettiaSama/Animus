# 旧心跳线路摸排清单与迁移记录（wake registration 第二批）

> 2026-10-03 · 前置：wake-registration-prd.md（契约）· 状态：M1–M4 已迁移

## 已迁移

| # | 线路 | 迁移前 | 迁移后 |
|---|---|---|---|
| M1 | `heartbeat/orchestrate/evolution.py` | `run_wander_evolution_step` 零调用死代码；`new_heartbeat_tick_id` 住在心跳包 | 前者删除；后者归位 `memory/heartbeat.py`；soul/service 两处 import 与 facade 表同步 |
| M2 | `ChecklistItem.channel` 字段 | 旧 dispatch 语义残留，全仓零读者 | 字段删除 |
| M3 | engine `schedule_daily_planner/review` | 写好从未激活（零调用方）：08:00 读 timeline 排今日计划、22:00 复盘写入长期记忆（LLM 经 TaskRunner，含重试） | 新域入口 `runtime/scheduler/heartbeat.py`：interval 项（1h）幂等确保两个 cron 注册在 engine 时间轴上；engine 未绑定 skip；执行仍由 engine 时钟负责（复用任务基建）。心跳从此保证"每日 LLM 预约存在"，挂掉最多一个心跳周期自动补注册 |
| M4 | story 演化裸线程 | `story.tick` 内 `_maybe_evolve` 自起 `story-evolution` daemon 线程跑重 LLM（T-1h 地标提前 fill + echo 补稿），绕过 worker 护栏 | 收编进 `SoulEvolutionWorker`：`HeartbeatContext` 新增 `orchestrator` 句柄；orchestrator 新增 `submit_heavy(item)`（一次性重任务，不进注册表，固定 id 借 worker pending 去重防重入）；`StoryRuntime.maybe_submit_evolve(orchestrator)` 保留容量门/inflight 双保险 |

## 摸排过但不迁（理由）

| 线路 | 现状 | 不迁理由 |
|---|---|---|
| react medium-term 定时归并 | 仅对话轮写入路径触发，无人对话永不压缩 | `_rewrite` 整文件重写跨实例无文件锁，心跳线程归并与 tao loop append 有竞态；间隔门已持久化（`medium_term_consolidate.json`），补上文件锁设计后即可挂 daily 项 |
| anchor outbound 主动出站泵 | presence-external-scan 产出的主动开聊意图堆在占位内存队列 | 投递渠道（ChannelRouter/speak 通道）未定，先设计后挂 interval 项 |
| speak 秒级预约（silence_break 90s / enter_greeting 12s 自建 Timer） | 各自持 DomainWorker + timer | 待"秒级归 speak 轮询线、分钟级以上归心跳"的粒度划界拍板；如归心跳需补 schedule_once 原语 |
| flow `HumanEditChannel.watch` | flow 运行期 asyncio mtime 轮询 | 作用域语义（运行中可人工编辑），非常驻工作 |
| memory telemetry drain 线程 | 常驻但事件驱动落盘 | 非周期任务 |
| clock→heartbeat poking 旧接口 | `HeartbeatProtocol` 结构在、电气断（三处 engine 构造均 heartbeat=None，`trigger_proactive_now` 零调用） | 保留协议兼容（webui 仍用 recent_log/force_tick）；不再回挂——回挂会与 HeartbeatCoreService 双驱动 tick |
| growth 引擎 / 输出审查官 | 各自常驻线程，事件/阈值驱动 | 非时钟工作，不属心跳职责 |
| webui 前端轮询 | 展示层 | UI 职责，不下沉 |

## 新契约下的接入方式（两步）

模块自写 `heartbeat.py` 暴露 `wake_items(cfg)` + `target(payload, ctx)` 入口；
在 `soul/wiring/heartbeat.py` 汇集表加一行。运行期派生重活用
`ctx.orchestrator.submit_heavy(item)`（固定 id 防重入）。
