# agent/soul

Soul 子系统承载跨会话主体状态：Memory、Life、Presence、Persona、Speak 与 Heartbeat。组合根是 `src/agent/soul/service.py` 中的 `SoulService`。

## 文档索引

- [memory](./memory/README.md)：事件/社交记忆图与 MySQL/JSON 后端
- [heartbeat](./heartbeat/README.md)：Soul 自有时间线、checklist 与注入邮箱
- [life](./life/README.md)：体验单元、虚拟/锚点叙事与 Storyview
- [presence](./presence/README.md)：当下态、期待、分享队列与主动发话
- [persona](./persona/README.md)：画像、buffer、self concept 与 distill
- [speak](./speak/README.md)：`request_driven`、`rhythm` 与真实出站

## `SoulService` 门面

```text
SoulService
├── dispatch(SoulRequest)                 life/memory/persona/speak 命令总线
├── speak_run_turn / ingest_presence_event 等跨域编排入口
├── accounts                              infra.accounts.AccountService
├── presence                              PresenceService
├── workers                               SoulWorkers
├── heartbeat / orchestrator              HeartbeatModule / HeartbeatOrchestrator
└── 内部组合
    ├── PersonaHandler / MemoryHandler / LifeHandler / SpeakHandler
    ├── SpeakService / LifeExperienceStack
    └── StoryService + storyview.StoryPort
```

`SoulRequest` 的 domain 仅有 `life`、`memory`、`persona`、`speak`。Presence 是编排 API，不在命令总线中；Accounts 与 Storyview 也不是 Soul domain。

只读 action 在 `idle` 和 `running` 可访问；写操作要求 `running`。`stopped` 后所有 dispatch 均拒绝。

## 生命周期

状态单向变化：

```text
idle --start()--> running --stop()--> stopped
```

- 重复 `start()`（已 running）和 `stop()`（仍 idle）是空操作。
- `stopped` 不能重新 `start()`；需要新建 `SoulService`。
- `start()` 依次初始化 Memory infra/热激活、Life、Persona、Storyview，接线 workers、Presence、Experience、Speak、Accounts 和 Heartbeat，最后进入 `running`。
- `stop()` 先执行 Presence/Memory sleep，再停止 core heartbeat、evolution worker、Speak 和域 workers，最终进入 `stopped`。

### workers

`SoulWorkers` 管理五个域 worker：

| worker | 来源 |
|---|---|
| memory | `SoulWorkers` 自建 `DomainWorker` |
| presence | `SoulWorkers` 自建 `DomainWorker` |
| persona | `SoulWorkers` 自建 `DomainWorker` |
| life | 注册 `LifeManager.worker`（`LifeService`） |
| story | 注册 `StoryService` |

启动顺序是 story → memory → presence → life → persona；停止顺序是 life → story → persona → presence → memory。Heartbeat 的 `SoulEvolutionWorker`、`HeartbeatCoreService` 线程，以及 Speak 的 compose/director/social workers 不属于这五个 worker。

## Accounts、Storyview 与 storage backend

`SoulService` 从 `DBConfig.resolved_storage_backend()` 得到同一个后端选择，并传给 Memory、Accounts 和 Storyview：

- `storage.backend=mysql`：要求 `mysql_client`。
- `storage.backend=json`：使用 `JsonStorageService(json_root)`，默认根目录 `.react/soul_db`。
- `storage.backend=auto`：MySQL 被禁用或连通探测失败时选 JSON，否则选 MySQL。

Accounts 位于 `src/infra/accounts/`，维护 `account_id ↔ interactor_id`，注册访客后回调 Memory 创建外部交互者；`bind_visitor()` 再绑定 Memory channel 与 Speak session。

Storyview 位于 `src/storyview/`。`StoryService` 是按 `world_id` 串行的 worker，`StoryPort` 是 Soul/Life/Speak 的同步访问边界。启动时会初始化 schema、默认 worldview/scene，并把 world 绑定到 Life profile。

JSON 后端是本地持久化实现，不是共享数据库：没有跨进程事务或并发一致性保证，不应描述为生产级 MySQL 等价物。

## 当前主数据流

```text
用户输入
  → SpeakService.run_turn
  → 默认 request_driven
  → 导演给 gate/节奏计划
  → Compose + 主会话 LLM 生成正文
  → DeliveryExecutor/返回值
  → LifeExperienceStack → Presence / chronicle / Memory

heartbeat-core 线程
  → HeartbeatModule.tick
  → HeartbeatOrchestrator checklist
  → SoulService API / evolution worker

Life landmark / surprise
  → storyview.StoryPort
  → StoryService worker
  → StoryEngine
```

## 接入边界

- 主动消息只有注册了 UI agent-initiated handler 或 Speak stream port 时才会到达外部客户端；否则仍可完成内部 session/experience 记账，但不能宣称已经发送给用户。
- Scheduler 只为少量可选任务摘要和 preflight 提供数据；Soul heartbeat 的周期线程与 checklist 不依赖 Scheduler 驱动。
- Qdrant/embedding 是 Memory 可选增强；JSON backend 会禁用默认向量 infra。

Tao 适配器位于 `src/agent/adapters/soul_tao/`，不是 `agent/soul/handlers/tao/`。
