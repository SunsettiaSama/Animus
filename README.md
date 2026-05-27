# ReAct Workstation

**ReAct 工作站**：面向日常使用的统一运行环境——在本地或容器化部署下一套入口即可驱动 ReAct 智能体、多轮对话、Plan 编排、记忆与知识库、定时任务与 Web 操作台。

- **运行时**：`python src/run.py`（默认 WebUI；可选 CLI、`--check` 健康检查、SearXNG 容器管理）
- **详细说明**：[docs/README.md](docs/README.md)（架构、模块状态、快速代码示例）
- **容器与观测**：[`docker/README.md`](docker/README.md)（Compose、管理容器、Grafana/Prometheus/Loki 等）

本仓库正从「框架型项目」演进为**可长期驻留的工作站形态**：同一套配置与数据目录支撑开发调试与生产部署，通过 WebUI 完成交互与编排，通过 `docs/` 分层文档维护各子系统约定。

---

## 模块

| 模块 | 路径 | 说明 |
|---|---|---|
| Soul | `src/agent/soul/` | 见下文 |
| Agent · ReAct | `src/agent/react/` | |
| Agent · Flow | `src/agent/flow/` | |
| Agent · Interaction | `src/agent/interaction/` | |
| Agent · Posture | `src/agent/posture/` | |
| Agent · Session | `src/agent/session/` | |
| Agent · Adapters | `src/agent/adapters/` | |
| Infra | `src/infra/` | |
| Runtime | `src/runtime/` | |
| Config | `src/config/` | |
| WebUI | `src/webui/` | |
| TTS / STT | `src/tts/` | |
| Embedding | `src/embedding/` | |
| Train | `src/train/` | |
| Test | `src/test/` | |

---

## Soul

Soul 是本仓库对智能体**长期主体性**的实现：在 ReAct 推理环（`TaoLoop`）之外，承载会随时间积累、演化、并在合适时机主动介入的「内在生命」——记忆、人格、生活叙事、当下态与心跳，而不是每轮对话从零开始的 Stateless LLM。

### 设计定位

ReAct 环负责**当下推理与行动**（读上下文 → 调 LLM → 执行工具 → 返回答案）。Soul 负责**跨会话的持久状态**：

- **记住**：对话事实经提炼写入 Redis STM / MySQL LTM，按需检索而非默认灌入 Prompt
- **成为**：画像、技能、偏好、情绪与自我信念随轮次演化，注入系统 Prompt
- **经历**：体验 → 账本 → 手账 → 叙事，形成可读的「生活史」
- **在场**：多维度 FSM 描述当下生理 / 情绪 / 认知 / 行为等状态，冲动累积后可向顶层发起主动交互
- **醒来**：心跳周期读取清单、触发重构与日终回顾，必要时 escalate 子 Agent

Soul 与 `agent/react/context`（会话 Step 轨迹 + 中期 JSONL）并行分工：前者是**主体记忆与人格**，后者是**当前对话的工作记忆**。

### 顶层入口：`SoulService`

`SoulService`（`src/agent/soul/service.py`）是 Soul 子系统的唯一门面，集中配置、生命周期与双通道访问：

```
SoulService
├── dispatch(SoulRequest)     # 统一命令总线（domain × action × channel）
├── query_* / record_* / speak_turn
├── start() / stop()          # idle → running → stopped
│
├── persona   → PersonaHandler      # 人格演化
├── memory    → MemoryHandler       # STM / LTM 记忆单元
├── life      → LifeHandler         # 体验 / 手账 / 叙事
├── speak     → SpeakHandler        # 对话 compose → LLM → stream → 记账
├── presence  → PresenceService     # 当下态 FSM + 主动 outbound
├── tao       → BaseTaoHandler      # ReAct 侧工具与 Prompt 块注册
├── workers   → SoulWorkers         # 后台域任务
└── orchestrator → HeartbeatOrchestrator  # bind_heartbeat 后
```

请求模型：`SoulRequest(domain, action, payload, channel)`，其中 `domain ∈ {life, memory, persona, speak}`，`channel ∈ {api, tao}`。只读 API 在 `idle` / `running` 均可访问；写入与演化仅在 `running` 下允许。

`TaoLoop` 可直接注入已有 `SoulService`，或在 `PersonaConfig` 启用时自建并 `start()`，随后挂载各域 handler 及 Soul 专属工具（`register_soul_tools`）。WebUI / HTTP 对话可走 `SpeakService.run_turn` 独立链路。

### 子系统

#### memory — 单元化持久记忆

路径：`src/agent/soul/memory/`

以 **Redis 短期记忆（STM）** + **MySQL 长期记忆（LTM）** 为核心，记忆抽象为 `MemoryUnit`（`factual` / `reconstructive` / `narrative` 三类），带激活度、情绪价态与半衰期衰减。轮末 `TurnWriter` 提炼写入 STM；心跳 `RuminationWriter` 做重构；日终 `NarrativeWriter` 编织叙事。检索经 `MemoryRetriever`（recent / semantic / hybrid），默认**不**自动注入 Prompt，由 `memory_recall` 工具或 Soul API 按需召回。

→ 详见 [docs/agent/soul/memory/README.md](docs/agent/soul/memory/README.md)

#### persona — 人格与自我概念

路径：`src/agent/soul/persona/`

三层结构：`PersonaManager` / `PersonaService` 维护 **profile**（静态画像）、**buffer**（体验聚类 + 月度漂移调度）、**self_concept**（慢变自我叙事，信念分级 emerging → core）。快变情绪在 `PresenceState.affect`，不在 persona 域。

→ 详见 [docs/agent/soul/persona/README.md](docs/agent/soul/persona/README.md)

#### life — 生命体验与叙事

路径：`src/agent/soul/life/`

四层结构：**体验 → Chronicle → 手账 → 叙事**。`LifeExperienceStack` 共享编排器，分 **dialogue** / **life** 两条 pipeline，与 Presence 双向绑定。`LifeManager` 统一对外；虚拟层（`virtual/`）与锚点层（`anchor/`）并列。

→ 详见 [docs/agent/soul/life/README.md](docs/agent/soul/life/README.md)

#### heartbeat — 主动心跳

路径：`src/agent/soul/heartbeat/`

双轨：`HeartbeatModule` 读 `HEARTBEAT.md` 做 LLM precheck / escalate；`HeartbeatOrchestrator` 扫描 checklist 驱动 Soul 各域演化（wander / landmark / drift / presence scan）。与 `runtime.scheduler.SchedulerEngine` 协议对接。

→ 详见 [docs/agent/soul/heartbeat/README.md](docs/agent/soul/heartbeat/README.md)

#### presence — 当下态

路径：`src/agent/soul/presence/`

**静态 FSM 四维度**（affect / somatic / cognition / perception）均为第一人称自叙；**动态交互层**（期待、冲动、分享意愿）在 `state/dynamic/` 与 `transition/interaction.py`。冲动达阈值经 `SpeakOutboundRouter` 触发主动对话。

→ 详见 [docs/agent/soul/presence/README.md](docs/agent/soul/presence/README.md)

#### speak — 对话编排

路径：`src/agent/soul/speak/`

`SpeakService` 完成 compose（persona + presence + share + recall）→ LLM → 流式 outbound → `LifeExperienceStack` 记账。含 session 生命周期、打断队列（`QueueDecisionRunner`）、内驱桥（`SpeakDriveBridge`）。

→ 详见 [docs/agent/soul/speak/README.md](docs/agent/soul/speak/README.md)

### 与 ReAct 推理环的接线

```
用户输入
    │
    ├─ SpeakService.run_turn（WebUI / HTTP 对话链路）
    │       compose → LLM → stream → LifeExperienceStack → Presence
    │
    └─ TaoLoop.stream()（ReAct 链路）
            ├─ context.recall()          ← react/context
            ├─ soul.persona blocks       ← Profile / SelfConcept / LifeProfile …
            ├─ LLM 推理 → 工具执行
            │       ├─ memory_recall
            │       └─ soul tao tools
            └─ post_process()
                    ├─ context.commit()
                    ├─ soul.memory.ingest_turn()
                    └─ soul.life / speak 记账

HeartbeatOrchestrator（AgentService 组装）
    └─ checklist → wander / landmark / drift / presence scan / escalate
```

Soul 因此不是 Prompt 里的一个块，而是**围绕 ReAct 环运行的持久子系统**：推理环读写 Soul 的状态，心跳与 Presence 在环外持续运转，使 Agent 具备时间维度上的连续主体。

→ Soul 总索引：[docs/agent/soul/README.md](docs/agent/soul/README.md)

---

## Agent · ReAct

---

## Agent · Flow

---

## Agent · Interaction

---

## Agent · Posture

---

## Agent · Session

---

## Agent · Adapters

---

## Infra

---

## Runtime

---

## Config

---

## WebUI

---

## TTS / STT

---

## Embedding

---

## Train

---

## Test
