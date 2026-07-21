# agent/soul/speak

**对话编排子系统**：在 Soul 域内完成会话入站 → Prompt 组装 → 生成 / 交付 → 流式出站 → 体验记账。与 `TaoLoop` 并行——HTTP / WebUI 走 `SpeakService.run_turn`；ReAct 环经 Tao 工具访问 Soul 各域。

源码：`src/agent/soul/speak/`。

---

## 设计目标：导演 vs 回复者

| 角色 | 职责 | 代码落点 |
|---|---|---|
| **导演（Director）** | 节奏与门控：说不说、分几段、等多久；下轮 prompt 块 refresh / include | `pipelines/request_driven/orchestrator/directors/`、`director/` |
| **回复者（Responder）** | 用组装好的 persona / presence / guidance / scene，由**主会话 LLM**生成角色台词 | 意图：`session/turn.py` → `SpeakLLMEngine`；见下方「当前缺口」 |

另有一层 **前台 / 后台** 编排：前台出本轮回复，后台预组装下一轮 `DirectorPlan` / `PreparedComposeFrame`（见 `OrchestratorTurnCoordinator`、demo `src/test/soul/speak/demo/dual_track_mvp_demo.py`）。

---

## 管线双轨

```text
SpeakPipelineName = "legacy_qa" | "request_driven"
DEFAULT_SPEAK_PIPELINE = "legacy_qa"    # 当前生产默认
```

| 管线 | 入口 | 谁写正文 | 状态 |
|---|---|---|---|
| **`legacy_qa`** | `LegacyQAPipelineRunner` → `run_session_turn` | 主会话 LLM | **默认、可跑**；仍会踢后台 Compose 预组装 |
| **`request_driven`** | `RequestDrivenPipelineRunner` → `_run_request_driven_turn` | 现状由 `TurnDeliveryDirector` 写 `segments[].text` | 演进主线，**回复者未闭合** |

路由：

```text
SpeakService.run_turn(..., pipeline=None)
  → normalize_speak_pipeline
  → UserInputItem.pipeline
  → SpeakPipelineRouter.run → LegacyQA | RequestDriven
```

显式指定：`run_turn(..., pipeline="request_driven")` 或 handler payload `pipeline`。

源码：`pipelines/types.py`、`pipelines/router.py`、`service.py`。

---

## 源码顶层

```
src/agent/soul/speak/
├── service.py                 # SpeakService — 门面、管线绑定、两轨回合
├── drive.py                   # SpeakDriveBridge — presence → should_speak
├── ports.py                   # Speak*Port
├── pipelines/
│   ├── types.py               # DEFAULT_SPEAK_PIPELINE / normalize
│   ├── router.py              # SpeakPipelineRouter
│   ├── legacy_qa/             # 一问一答：compose → 主 LLM → stream
│   └── request_driven/
│       └── orchestrator/      # 导演族、Compose、State、Delivery
│           ├── directors/     # DirectorCoordinator + 各导演
│           ├── director/      # ComposeDirector / decide_plan / plan store
│           ├── blocks/        # persona / guidance / memory / scene / …
│           ├── runtime/       # OrchestratorThread / DeliveryExecutor
│           ├── session/       # orchestrator 侧 session port
│           └── turn_coordinator.py
├── io/
│   ├── handler.py             # SpeakHandler（Soul dispatch）
│   ├── inbound/               # compose / memory / drive / presence / session
│   └── outbound/              # router / stream / life
├── session/                   # SpeakSessionManager、turn、队列、打断
├── llm/                       # SpeakLLMEngine（主会话 + 导演调用共用载体）
└── tools/                     # anchor / tao_delegate
```

顶层已无独立 `compose/`；组装逻辑在 `pipelines/request_driven/orchestrator/`。

---

## 导演清单（`DirectorCoordinator`）

入站并行第一批：`Outline` + `UserIntent` + `TurnDelivery` → `ModuleInject` → Memory/Share/Social → `SpeakGate`。

| 导演 | 决策 | LLM |
|---|---|---|
| `OutlineDirector` | rhythm_phase / step_label / step_goal | 是（失败 fallback） |
| `UserIntentDirector` | intent + confidence | 是 |
| `TurnDeliveryDirector` | 分段 + wait_ms + continuity；**现状含正文 text** | 是 |
| `SpeakGateDirector` | listen \| speak \| hold \| brew | 是 |
| `ModuleInjectDirector` | 写 `DirectorPlan` 块 refresh（可微调） | 规则为主 |
| `MemoryInjectDirector` | emergence / keyword / portrait 启发式 | 否（多进 cache） |
| `ShareImpulseDirector` | share preview include | 否 |
| `SocialArmDirector` | silence / social armed 透传 | 否 |
| `InterruptDirector` | push 中 reorder / cancel_unsent | 否 |

并存：`director/ComposeDirector` + `decide_plan`（后台预组装仍走此路径）。与 `ModuleInjectDirector` 同写 `DirectorPlanStore`，尚未统一。

导演 LLM：`DirectorLLMCaller`（低时延、并发门控）；不可用时走 `fallback_director_output`。

---

## 核心流程

### 默认轨：`legacy_qa`

```
SpeakService.run_turn
  → normalize → legacy_qa
  → _kick_for_upcoming_turn          # 后台：ComposeDirector / TurnCoordinator
  → SpeakPipelineRouter
  → LegacyQAPipelineRunner
  → run_session_turn
       compose_bundle → build_turn_system
       SpeakLLMEngine.generate / stream     ← 回复者（主模型）
       parse_agent_output → SpeakStreamPipeline
       record → LifeExperienceStack
```

### 演进轨：`request_driven`（现状）

```
SpeakService.run_turn(..., pipeline="request_driven")
  → _kick_for_upcoming_turn
  → OrchestratorThread.submit_user_input_sync
       → DirectorCoordinator.on_user_input
            TurnDelivery → pending_delivery_plan（含 text）
            SpeakGate → speak_gate
  → _compose_bundle                  # 组装，但当前不喂主 LLM
  → DeliveryExecutor.execute(segments)   # 推送导演写出的 text
  → record（若有 answer）
```

### 主动 outbound（presence）

```
presence.discharge / expectation scan
  → SoulService._emit_presence_speak(SpeakRequest)
  → SpeakOutboundRouter.emit_presence
  → SpeakService.handle_proactive / deliver_agent_message
```

### 内驱评估

`SpeakDriveBridge` 读 `PresenceService.snapshot()`，经 `ShareDesireComposer.evaluate_drive()` 判断 `should_speak`。

---

## 当前缺口（补「最后一环」前的状态）

按严重度：

1. **回复者未闭合**：设计上导演只管节奏 / 注入，正文应由主 LLM 生成；`request_driven` 现状把正文交给 `TurnDeliveryDirector`，compose 不进主模型。
2. **默认不走新轨**：`DEFAULT_SPEAK_PIPELINE = "legacy_qa"`（构筑降级后的生产选择）。
3. **delivery plan 交接**：`OrchestratorThread._maybe_notify_delivery` 会 `take_pending_delivery_plan`；`_run_request_driven_turn` 主要读 pending / sync 返回值，易出现 `no_delivery_segments` / 空 answer。
4. **双导演未统一**：`ComposeDirector` 与 `DirectorCoordinator` / `ModuleInject` 并存；Memory/Share/Social 部分只进 `director_cache`。
5. **降级过粗**：导演 LLM 不可用时交付常落成固定短句 fallback。

目标闭合形态（意图）：

```text
导演 → DeliveryPlan（节奏：段数 / wait / gate，不含角色长文）
Compose → 主 LLM（回复者）→ 分段正文
DeliveryExecutor → 按 plan 推送
```

---

## SpeakAction 速查

| Action | 说明 |
|---|---|
| `open_session` / `close_session` | 会话生命周期 |
| `run_turn` | 完整一轮（经管线路由） |
| `record_dialogue` | 仅记账（无 LLM） |
| `deliver` / `generate` / `generate_stream` | 出站 / 生成变体 |
| `drive_snapshot` / `evaluate_drive` | 内驱快照与评估 |
| `working_memory` / `dialogue_state` | 对话工作记忆查询 |

---

## 与 Soul 其它域

| 域 | 集成点 |
|---|---|
| **presence** | compose / persona 块注入当下态；drive 读 impulse / share；主动 outbound |
| **persona** | identity / self_concept / presence 块经 orchestrator blocks |
| **memory** | recall handoff、warm buffer、emergence / portrait 注入计划 |
| **life/experience** | `record_turn` → `LifeExperienceStack.record_dialogue_turn` |
| **SoulService** | `speak_turn`（Command）/ `speak_run_turn`（Orchestration 热路径） |

---

## 建议阅读顺序

1. `pipelines/types.py` — 默认管线  
2. `service.py` — `run_turn` / `_run_request_driven_turn` / `_bind_pipeline_router`  
3. `pipelines/request_driven/orchestrator/directors/coordinator.py` — 导演编排  
4. `pipelines/request_driven/orchestrator/directors/turn_delivery.py` — 当前正文生产点  
5. `session/turn.py` — legacy 回复者对照  
6. `pipelines/request_driven/orchestrator/runtime/orchestrator_thread.py` — pending / delivery 交接  

---

## 相关文档

- [presence/README.md](../presence/README.md)（冲动 / 分享 / outbound 门控）
- [life/README.md](../life/README.md)（对话体验 pipeline）
- [agent/soul/README.md](../README.md)（SoulService 总览）
