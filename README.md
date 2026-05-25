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
├── query_* / record_*        # HTTP / Tao 工具的语义化薄封装
├── start() / stop()          # idle → running → stopped
│
├── persona   → PersonaHandler      # 人格演化
├── memory    → MemoryHandler         # STM / LTM 记忆单元
├── life      → LifeHandler           # 体验 / 手账 / 叙事
├── presence  → PresenceService       # 当下态 FSM + 主动 outbound
├── tao       → BaseTaoHandler        # ReAct 侧工具与 Prompt 块注册
└── workers   → SoulWorkers           # 后台域任务
```

请求模型：`SoulRequest(domain, action, payload, channel)`，其中 `domain ∈ {life, memory, persona}`，`channel ∈ {api, tao}`。只读 API 在 `idle` / `running` 均可访问；写入与演化仅在 `running` 下允许。

`TaoLoop` 可直接注入已有 `SoulService`，或在 `PersonaConfig` 启用时自建并 `start()`，随后挂载 `PersonaService`、`LifeManager`、`MemoryService` 及 Soul 专属工具（`register_soul_tools`）。

### 子系统

#### memory — 单元化持久记忆

路径：`src/agent/soul/memory/`

以 **Redis 短期记忆（STM）** + **MySQL 长期记忆（LTM）** 为核心，记忆抽象为 `MemoryUnit`（`factual` / `reconstructive` / `narrative` 三类），带激活度、情绪价态与半衰期衰减。轮末 `TurnWriter` 提炼写入 STM；心跳 `RuminationWriter` 做重构；日终 `NarrativeWriter` 编织叙事。检索经 `MemoryRetriever`（recent / semantic / hybrid），默认**不**自动注入 Prompt，由 `memory_recall` 工具或 Soul API 按需召回。

→ 详见 [docs/agent/soul/memory/README.md](docs/agent/soul/memory/README.md)

#### persona — 人格与自我概念

路径：`src/agent/soul/persona/`

「摘要 → 写入 → 注入」演化循环：`PersonaManager` / `PersonaService` 维护画像（Profile）、技能库（Skills）、自省（Reflection）、用户偏好（Preference）、叙事情感（Emotional），以及 `self_concept` 中的**信念分级**（emerging → established → core）。每轮 `TaoLoop.post_process` 后台触发演化，产出 PromptBlock 序列供下轮拼接。

→ 详见 [docs/agent/soul/persona/README.md](docs/agent/soul/persona/README.md)

#### life — 生命体验与叙事

路径：`src/agent/soul/life/`

四层结构：**体验（Experience）→ 客观记录（Chronicle）→ 手账地标（Journal）→ 反思叙事**。`LifeManager` 统一对外，`LifeProfileBlock` / `JournalBlock` 注入 Prompt；虚拟生命层（`life/virtual/`）与锚点内化（`life/anchor/`）扩展自主叙事与外部事件吸收。

→ 详见 [docs/agent/soul/life/README.md](docs/agent/soul/life/README.md)

#### heartbeat — 主动心跳

路径：`src/agent/soul/heartbeat/`

周期性读取 `HEARTBEAT.md` 清单，LLM precheck 判断是否需要介入（`ESCALATE` → 子 Agent），并与 `runtime.scheduler.SchedulerEngine` 通过协议对接。`HeartbeatCoreService` 可选将摘要写入注入邮箱，供下一轮对话合并上下文；日终钩子驱动 `LifeManager` 回顾。

→ 详见 [docs/agent/soul/heartbeat/README.md](docs/agent/soul/heartbeat/README.md)

#### presence — 当下态

路径：`src/agent/soul/presence/`

**四个 FSM 维度**均为 Agent 第一人称自叙（字符串），不再使用效价/强度等结构化指标：

| 维度 | 字段 |
|---|---|
| 情感 `affect` | `narrative` |
| 生理 `somatic` | `narrative` |
| 认知 `cognition` | `working_memory` / `thinking`（两段自叙）|
| 感知 `perception` | `narrative` |

对话期待、分享冲动与 outbound 门控位于 **`PresenceInteraction`**（`interaction.py`），不属于 FSM 维度，由 `capture` → `gate` 流水线驱动。

**起床 / 休眠**（`fsm/init/`）：心跳在每日 `presence_wake_at`（默认 `08:00`）调度 `PresenceWakeEngine`，以 LLM 生成四维度自叙完成 FSM 初始化（演化入口）；清醒窗口由 `HeartbeatConfig.active_hours_start/end` 控制（默认 `08:00`–`22:00`），窗口外自动休眠并停止心跳 tick。

### 与 ReAct 推理环的接线

```
用户输入
    │
    ▼
TaoLoop.stream()
    │
    ├─ context.recall()          ← 会话 Step + 中期 JSONL（react/context）
    │
    ├─ soul.persona blocks       ← Profile / Skills / Emotional / LifeProfile …
    │
    ├─ LLM 推理 → 工具执行
    │       ├─ memory_recall     ← Soul MemoryService 按需检索
    │       └─ soul tao tools    ← life / persona / memory 域操作
    │
    └─ post_process()（后台）
            ├─ context.commit()
            ├─ soul.memory.ingest_turn()
            ├─ soul.persona.evolve()
            └─ soul.life.record_experience()
                    │
                    ▼
            HeartbeatOrchestrator（常驻，AgentService 组装）
                    └─ tick → 重构记忆 / 日终回顾 / escalate
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
