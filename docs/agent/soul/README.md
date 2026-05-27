# agent/soul

Soul 子系统在 ReAct 推理环之外承载 **持久记忆**、**调度心跳**、**生活叙事与体验**、**当下态 FSM**、**对话编排（Speak）** 与 **人格演化**。`SoulService` 是统一门面；`TaoLoop` 可注入已有实例，或通过 `BaseTaoHandler` 走 Tao 通道访问各域。

---

## 文档索引

| 文档 | 说明 |
|---|---|
| [memory/README.md](./memory/README.md) | `MemoryService`，STM/LTM，检索与冲刷 |
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
├── memory/
├── heartbeat/
├── life/
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
