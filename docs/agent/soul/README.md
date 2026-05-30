# agent/soul

Soul 子系统在 ReAct 推理环之外承载 **持久记忆**、**调度心跳**、**生活叙事与体验**、**当下态 FSM**、**对话编排（Speak）** 与 **人格演化**。`SoulService` 是统一门面；`TaoLoop` 可注入已有实例，或通过 `BaseTaoHandler` 走 Tao 通道访问各域。

---

## 文档索引

| 文档 | 说明 |
|---|---|
| [memory/README.md](./memory/README.md) | `MemoryService`，记忆图（event/social），I/O 边界，涌现 / 反刍 / 睡眠 |
| [heartbeat/README.md](./heartbeat/README.md) | `HeartbeatModule`、`HeartbeatOrchestrator` 与调度对接 |
| [life/README.md](./life/README.md) | `LifeManager`、体验栈、虚拟层 / 锚点层 |
| [persona/README.md](./persona/README.md) | `PersonaManager` / `PersonaService`，画像 / buffer / self_concept |
| [presence/README.md](./presence/README.md) | `PresenceService`，当下态 FSM + 期待 / 冲动 / 分享 |
| [speak/README.md](./speak/README.md) | `SpeakService`，compose → LLM → stream → 记账 |

---

## 顶层入口：`SoulService`

源码：`src/agent/soul/service.py`。

```
SoulService
├── dispatch(SoulRequest)          # 统一命令总线（domain × action × channel）
├── query_* / record_* / speak_turn  # HTTP / Tao / 内部编排薄封装
├── start() / stop()               # idle → running → stopped
│
├── persona   → PersonaHandler
├── memory    → MemoryHandler
├── life      → LifeHandler
├── speak     → SpeakHandler
├── presence  → PresenceService     # 不经 handler，直接域服务
├── tao       → BaseTaoHandler      # ReAct 侧工具与 Prompt 块
├── workers   → SoulWorkers         # memory / life / presence 后台域任务
└── orchestrator → HeartbeatOrchestrator  # bind_heartbeat 后可用
```

请求模型：`SoulRequest(domain, action, payload, channel)`。

- `domain ∈ {life, memory, persona, speak}`
- `channel ∈ {api, tao}`（Tao 通道仅 persona 相关 action + ReAct 工具链）

只读 API（见 `access.READ_API_ACTIONS`）在 `idle` / `running` 均可访问；写入与演化仅在 `running` 下允许。

### 双轨入口（Command vs Orchestration）

| 轨道 | 代表 API | 用途 |
|------|----------|------|
| **Command** | `dispatch(SoulRequest)`、`speak_turn()` 等薄封装 | 可审计、可序列化的 domain×action；Heartbeat checklist 默认路径 |
| **Orchestration** | `run_wander`、`ingest_presence_event`、`speak_run_turn()` | 跨域顺序编排或 L0 热路径；仍在 `SoulService` 上收束 |

二者均为合法顶层 API；收束指 **调用方只依赖 `SoulService`**，而非「一切必须 dispatch」。

### 调用层次（L0 / L1 / L2）

| 层次 | 调用方 | 收束标准 |
|------|--------|----------|
| **L0** | WebUI、`TaoLoop`、`HeartbeatOrchestrator` | 只使用 `SoulService` 公开方法/属性；禁止 `_ensure_*`、`.handler.api` |
| **L1** | `SoulService` | 创建域服务、`SoulWorkers`、`start()` 内跨域 IO 桥接线 |
| **L2** | Handler → 本域 `*Service` → 子 Service | 不跨域 import 其他域 `service.py`；跨域经 L1 注入 Port |

### Service 清单与收束（L2 域服务）

| Service | 文件 | L1 入口 | L2 父级 |
|---------|------|---------|---------|
| `PersonaService` | `persona/service.py` | `PersonaHandler` | — |
| `MemoryService` | `memory/facade/service.py` | `MemoryHandler` | — |
| `LifeManager` / `LifeService` | `life/manager.py`, `life/service.py` | `LifeHandler` / worker | worker 由 LifeManager 持有 |
| `SpeakService` | `speak/service.py` | `SpeakHandler` + `speak_run_turn` 门面 | — |
| `PresenceService` | `presence/service.py` | `SoulService.presence`（无 Handler） | — |
| `RuminationService` | `memory/rumination/service.py` | — | `MemoryService` |
| `SleepService` | `memory/sleep/service.py` | — | `MemoryService` |
| `SpreadActivationService` | `memory/emergence/spread/service.py` | — | `MemoryService.emergence` |
| `SpeakSessionService` | `speak/session/service.py` | — | `SpeakService.session_manager` |
| `HeartbeatCoreService` | `heartbeat/core_service.py` | `SoulService` 侧车 | — |

### 旁路分类（A / B / C）

| 类 | 含义 | 示例 |
|----|------|------|
| **A** | L1 合法：组合根编排或 `start()` 显式桥接 | `_wire_workers()`、`run_wander`、Memory↔Speak session 回调 |
| **B** | L0 曾走私有通道；已收敛或待观察 | WebUI 原 `_ensure_speak_service().run_turn` → **`speak_run_turn`**；Tao 缓存 `.persona.service` / `.memory.api`（待门面化） |
| **C** | 层次泄漏：子域横向依赖具体实现 | `SpeakService(presence=...)`、`SpeakPromptComposer`→presence 类型、`LifeExperienceStack`↔`PresenceService`、Heartbeat `domain=="presence"` 字符串分支 |

### `ports.py` 与跨域缺口

已定义：`LLMServicePort`、`EmbeddingPort`、`ExternalOpportunitySupplier`、`SpeakExperiencePort`、`SpeakDialogueExperiencePort`、`PresenceSnapshotPort`（后者供后续收敛 C 类）。

| 跨域耦合 | 现状 | 建议 |
|----------|------|------|
| SpeakHandler → experience | 已收敛：`SpeakExperiencePort` + `SoulSpeakExperiencePort` | — |
| Speak → Presence 构造注入 | C：`PresenceService` 具体类型 | 改为 `PresenceSnapshotPort` 注入 |
| Life 体验栈 ↔ Presence | C：双向 bind | 仅 L1 `SoulService.start()` 接线 |
| Memory ↔ Speak 回调 | A：经 `SoulService._ensure_speak_service` 注册 | 保持 |
| Presence 无 `SoulDomain` | **架构决策**：Presence 仅 Orchestration API，不进 `SoulRequest` 总线；Heartbeat 走 `run_presence_*` | 文档定型，不新增 Handler |

### L0 公开 Speak 门面（WebUI 热路径）

- `speak_turn()` — 经 `dispatch`（Command）
- `speak_run_turn()` — 直调 `SpeakService.run_turn`（Orchestration 热路径）
- `speak_submit_user_input()`、`speak_is_pushing()`、`speak_session_trace_cache()`、`speak_initialized`

---

## 源码顶层

```
src/agent/soul/
├── service.py           # SoulService 门面
├── request.py           # SoulRequest / SoulDomain / SoulChannel
├── access.py            # 只读 action 白名单
├── ports.py             # LLM / Embedding / Tao 跨模块 Protocol
├── handlers/
│   ├── api/             # life / memory / persona action → handler
│   └── tao/             # BaseTaoHandler、Tao 工具与 Prompt 块
├── workers/             # SoulWorkers + DomainWorker
├── memory/              # 记忆图 + facade + io（session/life）+ emergence / rumination / sleep
├── heartbeat/
├── life/
│   ├── io/              # LifeIOHub：speak 入站 + memory 出站
│   ├── virtual/         # 虚拟叙事：journal / chronicle / surprise / narrative
│   ├── anchor/          # 现实锚点：inbound digest / outbound / chronicle
│   └── experience/      # LifeExperienceStack、dialogue/life pipeline
├── persona/
│   ├── profile/         # 静态画像
│   ├── buffer/          # 体验聚类 + 月度漂移调度
│   └── self_concept/    # 慢变自我叙事
├── presence/
│   ├── state/           # static（affect/somatic/cognition/perception）+ dynamic（expectation/interaction）
│   ├── transition/      # wake/sleep、boundary、life_sync、interaction
│   └── service.py       # PresenceService
└── speak/
    ├── compose/         # Prompt 组装（persona/presence/share/recall/context）
    ├── io/              # inbound / outbound / stream
    ├── session/         # 生命周期、打断队列、语义边界
    ├── llm/             # SpeakLLMEngine
    ├── drive.py         # SpeakDriveBridge（presence → should_speak）
    └── service.py       # SpeakService
```

---

## 跨域数据流（概要）

```
用户输入
    → SpeakService.run_turn
        → compose（persona + presence + share + context）
        → LLM / stream outbound
        → record_turn → LifeExperienceStack.record_dialogue_turn
            → DialogueExperiencePipeline → Presence 直写
            → ExperienceOrchestrator.ingest → memory / chronicle
            → after_ingest → presence.pull_and_sync_from_life

presence 冲动 / 期待 scan
    → SoulService._emit_presence_speak
    → SpeakOutboundRouter → SpeakService.handle_proactive

heartbeat tick
    → HeartbeatOrchestrator.run_due（checklist）
    → dispatch 各域 action（wander / landmark / drift / presence scan …）
    → memory tick → EmotionalSignal → presence
```

Soul 与 `agent/react/context`（会话 Step 轨迹 + 中期 JSONL）并行：**Soul 是跨会话主体状态，context 是当前对话工作记忆**。

---

## 相关文档

- [agent/react/README.md](../react/README.md)（TaoLoop 与 Soul 接线）
- [agent/service/README.md](../service/README.md)（AgentService 组装 heartbeat）
- [storage/README.md](../../storage/README.md)（`.react/life/`、`.react/persona/` 布局）
