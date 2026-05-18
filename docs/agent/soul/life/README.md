# agent/soul/life

**生命体验子系统**：在 Tao 会话与心跳之间，以「体验 → 客观记录 → 手账 → 反思」四层结构持续累积 Agent 的主观生命状态，并通过三个可热注入的 LLM 协议将机械流水线连接至真实叙事生成。

源码：`src/agent/soul/life/`。

---

## 顶层导出

```python
from agent.soul.life import (
    # 体验层
    ExperienceUnit, ExperienceAction, ExperienceActionKind,
    ExperienceFeeling, ExperienceSituation,
    ExperienceLog, ExperienceBuilder,
    ExperienceCollapser, NullCollapser,
    # 编排层
    ExperienceOrchestrator, MemoryIngestPort,
    # 客观事实层
    ChronicleEntry, ChronicleKind, ChronicleStore,
    # 手账层
    Landmark, LandmarkStatus, LandmarkFiller, NullLandmarkFiller,
    DiceResult, roll_d100,
    MAX_DAILY_LANDMARKS, K_RECENT_LANDMARKS,
    LifeJournal, JournalStore,
    # 服务层
    LifeService,
    # 统一入口 & Prompt 块
    LifeManager, LifeProfileBlock, JournalBlock,
)
```

---

## 目录结构

```
src/agent/soul/life/
├── __init__.py
├── manager.py              # LifeManager：新旧桥接的统一入口
├── service.py              # LifeService（BaseServiceManager）：后台线程
├── orchestrator.py         # ExperienceOrchestrator + MemoryIngestPort
├── block.py                # LifeProfileBlock、JournalBlock → PromptBlock
├── experience/
│   ├── unit.py             # ExperienceUnit = 情境 + 行动 + 感受
│   ├── log.py              # ExperienceLog（热窗口 JSONL，默认 2 小时）
│   ├── builder.py          # ExperienceBuilder：构造 + ingest + chronicle
│   └── collapser.py        # ExperienceCollapser Protocol + NullCollapser
├── chronicle/
│   ├── entry.py            # ChronicleEntry / ChronicleKind
│   └── store.py            # ChronicleStore（永久追加 JSONL）
├── journal/
│   ├── item.py             # Landmark + LandmarkStatus（MAX=3/K=5）
│   ├── dice.py             # DiceResult + roll_d100()
│   ├── filler.py           # LandmarkFiller Protocol + NullLandmarkFiller
│   ├── journal.py          # LifeJournal：地标轴 + 自述
│   └── store.py            # JournalStore → journal.json
├── ledger/                 # 旧有路径（heartbeat / 日回顾依赖）
│   ├── event.py
│   ├── log.py
│   └── evolution.py
└── narrative/              # 旧有路径（画像生成 / 日综合依赖）
    ├── arc.py
    ├── event.py
    ├── event_log.py
    ├── evolution.py
    ├── profile.py
    └── synthesis.py
```

---

## 架构分层

### 四层职责

| 层 | 模块 | 时态 | 职责 |
|---|---|---|---|
| **体验层** | `experience/` | 先验·即时 | 原始输入 → ExperienceUnit |
| **编排层** | `orchestrator.py` | 无状态·机械 | 热存储 + 显著性擢升 + 交会折叠 |
| **事实层** | `chronicle/` | 过去·客观 | 已发生事件的永久账本，只增不删 |
| **手账层** | `journal/` | 当下·主观 | Agent 自主的议程与自述 |

### 两条独立链路

**用户交互链路（被动·先验）**

```
user_text + agent_reply
    → ExperienceBuilder.record_user_turn()
    → ExperienceUnit(source="user")
    → ExperienceOrchestrator.ingest()
    → ChronicleStore(ChronicleKind.user_turn)
```

**叙事链路（主动·预约）**

```
LifeJournal.add_landmark(intention, scheduled_at)
    ↓ 到点 / 服务重启发现超时
roll_d100() → DiceResult（体验基调：10级描述，d100随机）
LandmarkFiller.fill(landmark, profile, memories, recent_landmarks, dice)
    → narrative 文本
ExperienceBuilder.record_story_beat()
    → ExperienceUnit(source="narrative")
    → ExperienceOrchestrator.ingest()
    → ChronicleStore(ChronicleKind.landmark)
    → Landmark.mark_done(narrative, experience_id, dice_value, dice_tendency)
```

### 交会折叠（编排层）

当 `source="user"` 与 `source="narrative"` 的体验单元时间戳相差不足 **30 分钟**，`ExperienceOrchestrator` 自动检测碰撞并调用 `ExperienceCollapser`：

```
user_unit + narrative_unit
    → ExperienceCollapser.collapse()
    → merged_text（"这两件事交会时发生了什么"）
    → ExperienceUnit(source="collision", feeling=清零)
    → ingest（原两个 unit 标记为已折叠，不再重复处理）
```

### 显著性擢升

所有 unit 进入 `ExperienceOrchestrator.ingest()` 后：
- `feeling.salience ≥ salience_threshold`（默认 0.5）→ 立即推送至 `MemoryIngestPort`
- 心跳 `tick()` 批量扫描热窗口，二次检查 + 清仓过期体验

### 反思闭环

```
run_daily_review()
    → LLM 生成新 LifeProfile
    → profile.narrative 回写 journal.set_narrative()  ← 自述更新
    → life_service.update_context(profile_narrative)   ← 推送到下次填充上下文
```

---

## 三个 LLM 注入口

均通过 `LifeManager` 热注入，系统在无 LLM 时以占位实现正常运行：

| 协议 | 方法签名 | 作用 | 占位实现 |
|---|---|---|---|
| `LandmarkFiller` | `fill(landmark, profile_narrative, recent_memories, recent_landmarks, dice) → str` | 地标 → 完整情节文本 | `NullLandmarkFiller` |
| `ExperienceCollapser` | `collapse(user_unit, narrative_unit) → str` | 交会 → 重新表述 | `NullCollapser` |
| `MemoryIngestPort` | `ingest_experience(unit) → None` | 擢升 → 长期记忆 | 由 `MemoryService` 实现 |

```python
life = LifeManager(life_dir, llm=llm)
life.set_memory_port(memory_service)
life.set_landmark_filler(my_llm_filler)
life.set_collapser(my_llm_collapser)
```

---

## 手账（LifeJournal）

Agent 每天预约 **1~3 个地标**（`MAX_DAILY_LANDMARKS = 3`），每个地标包含：

- `intention`：想做什么（一句话）
- `scheduled_at`：预定触发时间（ISO 8601）
- `context`：触发条件或背景（可空）
- `dice_value` / `dice_tendency`：填充时的骰点与基调（回填，永久保存）
- `narrative`：LLM 生成的完整情节（填充后回填）
- `experience_id`：关联的 ExperienceUnit（可追溯）

**地标状态机**：`pending → processing → done`；重启时 `pending` 且已超时 → `overdue → processing → done`。

**命运骰**（`roll_d100()`）在填充前投掷，返回 1~100 点数及对应体验基调（10 级描述），直接注入叙事引擎 prompt，由 LLM 自行解读走向。

**手账 Prompt 注入**：`JournalBlock` 渲染「今日地标进度 + 近期经历摘要 + 自述」注入 TaoLoop 对话上下文。

---

## 典型调用关系

| 调用方 | 行为 |
|---|---|
| `TaoLoop.post_process` | `LifeManager.record_turn(q, a)` → `LifeService.enqueue_user_turn()` |
| `TaoLoop`（prompt 组装） | `JournalBlock(life.journal)`、`LifeProfileBlock(life.profile)` |
| `TaoLoop`（初始化） | `life.set_memory_port(memory_service)` |
| `HeartbeatModule` | 调度摘要 → `record_scheduler_digest_from_heartbeat`；跨日 → `run_daily_review` |
| `run_wander_evolution_step` | `life_port.receive_experience(result)` → `enqueue_story_beat` |
| Agent 自主（可选） | `life.add_landmark(intention, scheduled_at)` → 手账写入 + 持久化 |
| 进程收尾 | `LifeManager.stop()` → `LifeService.stop()` |

---

## 存储文件（`StorageConfig.life_dir`）

| 文件 | 说明 |
|---|---|
| `experience_hot.jsonl` | 体验热窗口（`ExperienceLog`，超时由 `purge_old` 清仓） |
| `chronicle.jsonl` | 客观事实永久账本（`ChronicleStore`，只增不删） |
| `journal.json` | 手账状态快照（`JournalStore`） |
| `life_profile.json` | 当前生活状态画像（`LifeProfileStore`） |
| `tao_dialogue.jsonl` | Tao 对话账本（`LedgerEventLog`，旧有路径） |
| `narrative_events.jsonl` | 叙事事件（`NarrativeEventLog`，旧有路径） |
| `story_arc.json` | 章节弧持久化（`StoryArcStore`，旧有路径） |

详见 [storage](../../../storage/README.md) 总览。

---

## 相关文档

- [agent/soul/README.md](../README.md)
- [agent/soul/heartbeat](../heartbeat/README.md)
- [agent/soul/memory](../memory/README.md)（`ingest_experience` / Soul STM）
- [agent/soul/persona](../persona/README.md)（`EmotionalState` / `SelfConcept` 漂移）
- [agent/react/README.md](../../react/README.md)（`TaoLoop` 与 Life 块）
- [storage](../../../storage/README.md)
