# agent/soul/life

**生命体验子系统**：在 Tao 会话、Speak 对话与心跳之间，以「体验 → 客观记录 → 手账 → 叙事」结构持续累积 Agent 的主观生命状态。虚拟叙事层（`virtual/`）与现实锚点层（`anchor/`）并列；共享 `LifeExperienceStack` 编排对话与生活两条 pipeline。

源码：`src/agent/soul/life/`。

---

## 顶层导出

```python
from agent.soul.life import (
    LifeManager, LifeService,
    ExperienceUnit, ExperienceBuilder, ExperienceOrchestrator,
    LifeExperiencePipeline,
    ChronicleEntry, ChronicleStore,
    AnchorChronicleStore, AnchorLayer, RealityAnchorLayer,
    LifeJournal, Landmark, LandmarkFiller, roll_d100,
    VirtualLayer, NarrativeEngine, SurpriseGenerator,
    LifeProfile, LifeProfileBlock, JournalBlock,
)
```

对话体验栈（经 `SoulService.experience`）：

```python
from agent.soul.life.experience.stack import LifeExperienceStack
```

---

## 目录结构

```
src/agent/soul/life/
├── manager.py                # LifeManager — 统一对外入口
├── service.py                # LifeService — 后台线程（landmark / surprise tick）
├── orchestrator.py           # 生活层编排（与 experience/orchestrator 区分）
├── block.py                  # LifeProfileBlock / JournalBlock
├── profile.py                # LifeProfile / LifeProfileStore
├── ports.py                  # 跨层 Protocol
├── life_bridge.py            # LifeContextInput
├── narrative_context.py      # StoryWorldContextSupplier
├── experience/
│   ├── stack.py              # LifeExperienceStack（共享编排器 + 双 pipeline）
│   ├── orchestrator.py       # ingest / 擢升 / 折叠 / chronicle 路由
│   ├── pipeline.py           # LifeExperiencePipeline（非对话生活体验）
│   ├── builder.py            # ExperienceBuilder
│   ├── unit.py / log.py / collapser.py / sources.py
│   ├── incident.py           # LifeIncident
│   └── dialogue/             # DialogueExperiencePipeline / coordinator / working_memory
├── virtual/                  # 虚拟叙事层
│   ├── layer.py              # VirtualLayer
│   ├── chronicle/            # VirtualChronicleStore
│   ├── journal/              # LifeJournal / Landmark / dice / filler
│   ├── narrative/            # NarrativeEngine
│   ├── surprise/             # SurpriseGenerator
│   └── review/               # 日终回顾上下文
└── anchor/                   # 现实锚点层
    ├── layer.py              # AnchorLayer / RealityAnchorLayer
    ├── chronicle/            # AnchorChronicleStore
    ├── inbound/              # digest 吸收外部事件
    ├── outbound/             # ProactiveOutboundPort
    └── presence_bundle.py    # Presence 体验 bundle
```

---

## 架构分层

### 四层职责

| 层 | 模块 | 时态 | 职责 |
|---|---|---|---|
| **体验层** | `experience/` | 先验·即时 | 原始输入 → ExperienceUnit |
| **编排层** | `ExperienceOrchestrator` | 无状态·机械 | 热存储 + 显著性擢升 + 交会折叠 + chronicle |
| **事实层** | `virtual/chronicle/` + `anchor/chronicle/` | 过去·客观 | 虚拟 / 锚点两套永久账本 |
| **手账层** | `virtual/journal/` | 当下·主观 | 地标议程与自述 |

### LifeExperienceStack

```
LifeExperienceStack
├── orchestrator          # 共享 ExperienceOrchestrator
├── dialogue              # DialogueExperiencePipeline（Speak 对话记账）
├── life                  # LifeExperiencePipeline（landmark / wander / incident）
└── bind_presence()       # ↔ PresenceService 双向直连
```

对话 turn 经 `SpeakService.record_turn` → `stack.record_dialogue_turn()` → dialogue pipeline 直写 Presence → orchestrator ingest → memory / chronicle → `after_ingest` sync presence。

### 两条独立链路

**用户交互（被动）**

```
user_text + agent_reply
    → ExperienceBuilder.record_user_turn()
    → ExperienceOrchestrator.ingest()
    → VirtualChronicleStore / AnchorChronicleStore
```

**叙事地标（主动）**

```
LifeJournal.add_landmark()
    → roll_d100() → LandmarkFiller.fill()
    → ExperienceBuilder.record_story_beat()
    → ingest → chronicle
```

### 交会折叠

`source="user"` 与 `source="narrative"` 时间戳相差不足 30 分钟时，`ExperienceCollapser` 合并为 `source="collision"` 单元。

---

## 三个 LLM 注入口

| 协议 | 作用 | 占位 |
|---|---|---|
| `LandmarkFiller` | 地标 → 情节文本 | `NullLandmarkFiller` |
| `ExperienceCollapser` | 交会折叠 | `NullCollapser` |
| `MemoryIngestPort` | 显著性擢升 → LTM | 由 `MemoryService` 实现 |

---

## 典型调用关系

| 调用方 | 行为 |
|---|---|
| `SpeakService.record_turn` | → `LifeExperienceStack.record_dialogue_turn` |
| `SoulService.record_dialogue_turn` | 门面 → experience stack |
| `HeartbeatOrchestrator` | `PLAN_LANDMARK` / `TRIGGER_LANDMARKS` / `TICK_SURPRISE` |
| `run_wander_evolution_step` | memory wander → life experience ingest |
| `TaoLoop`（legacy） | `LifeManager` + `JournalBlock` / `LifeProfileBlock` |
| `LifeManager.stop()` | → `LifeService.stop()` |

---

## 存储文件（`StorageConfig.life_dir`）

| 文件 | 说明 |
|---|---|
| `experience_hot.jsonl` | 体验热窗口 |
| `chronicle.jsonl` | 虚拟 chronicle（`VirtualChronicleStore`） |
| `anchor_chronicle.jsonl` | 锚点 chronicle |
| `journal.json` | 手账快照 |
| `life_profile.json` | 生活状态画像 |

详见 [storage](../../../storage/README.md)。

---

## 相关文档

- [speak/README.md](../speak/README.md)（对话 turn 记账入口）
- [presence/README.md](../presence/README.md)（bind_presence 同步）
- [memory/README.md](../memory/README.md)（`ingest_experience`）
- [heartbeat/README.md](../heartbeat/README.md)（landmark / wander 调度）
