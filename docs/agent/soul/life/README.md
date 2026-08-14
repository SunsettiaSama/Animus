# agent/soul/life

Life 把对话、主动事件和虚拟叙事整理成 `ExperienceUnit`，维护热体验、客观 chronicle、主观 journal，并通过 `storyview.StoryPort` 推进故事世界。

## 当前目录

```text
src/agent/soul/life/
├── manager.py / service.py
├── io/
│   ├── speak/                       Speak 入站
│   └── memory/                      Memory 出站
├── experience/
│   ├── domain/                      ExperienceUnit、source、codec
│   ├── hub/stack.py                 LifeExperienceStack
│   ├── dialogue/                    对话 pipeline/session/working memory
│   ├── ingest/                      builder、life pipeline、incident、presence
│   ├── unit_layer/
│   │   ├── create/
│   │   ├── manage/                  log、orchestrator、collapser
│   │   └── promote/                 memory policy/dispatch/port
│   └── skills/                      压缩块体验编写入口
├── virtual/
│   ├── chronicle/
│   ├── episode/
│   ├── journal/
│   │   ├── agenda/
│   │   └── legacy/
│   ├── narrative/
│   ├── review/
│   └── surprise/
└── anchor/
    ├── chronicle/
    ├── inbound/
    └── outbound/
```

旧文档中的 `experience/builder.py`、`experience/pipeline.py`、`experience/orchestrator.py`、`virtual/journal/agenda.py` 等平铺路径已不再对应当前代码。

## Experience 架构

```text
LifeExperienceStack
├── units: ExperienceUnitLayer
│   ├── create
│   ├── manage: ExperienceOrchestrator + ExperienceLog
│   └── promote: MemoryIngestPort
├── dialogue: DialogueExperiencePipeline
└── life: LifeExperiencePipeline
```

`SoulService` 构造 stack 后：

- 绑定 LifeManager 的 life/dialogue pipeline。
- 双向绑定 Presence。
- 将 Memory 的 `LifeExperienceMemoryIO` 写入 unit manager 与 life pipeline。
- 将 Speak lifecycle/recording 接到 dialogue pipeline。

对话记账：

```text
Speak record_dialogue
  → LifeSpeakIO
  → LifeExperienceStack.dialogue
  → ExperienceUnitLayer.manage
  → hot log / chronicle / Memory promotion
  → Presence on_unit_ingested + pull_and_sync_from_life
```

压缩块需要 LLM 的体验编写 skill；未配置 LLM 时会抛错，不能称为无依赖可用。

## 虚拟层、锚点层与 Storyview

- anchor：现实/用户交互 chronicle 与 proactive outbound intent。
- virtual：journal、landmark agenda、episode、narrative、surprise。
- Storyview：客观世界、scene、事件、GM 问答、故事弧与位置快照。

Life 本身不实现故事数据库。`VirtualLayer` 只持有 `storyview.port.StoryPort`；需要故事能力的方法会调用 `_require_story_port()`，未接线时抛 `RuntimeError`。

`SoulService.start()` 当前会创建并启动 `StoryService`，包装为 `StoryPort`，然后：

1. 设到 `LifeManager/VirtualLayer`。
2. 用 Speak 主 LLM 回答 GM question。
3. 从 `LifeProfile.world_id` 绑定世界。
4. 确保默认 scenes。
5. 通过 `StoryWorldContextBridge` 给 Life narrative 提供背景。
6. 同一 port 也注入 Speak scene block。

`StoryPort` 是 Soul 访问 Storyview 的唯一同步边界；底层 `StoryService` 是 story worker，按 `world_id` 串行执行。

## landmark / agenda

当前 journal 同时包含：

- `journal/legacy/`：旧 landmark 实体与兼容实现。
- `journal/agenda/`：新的日程 cue、planner、store、prompt 与工具。
- `journal/planner.py`：在两种 planning strategy 间编排。

典型故事链：

```text
compose/plan landmark or agenda
  → journal 保存意图
  → 到期 fill
  → StoryPort.ask_gm / answer_gm / distill_arc
  → NarrativeEngine 写主观结果
  → ExperienceUnit ingest
```

没有 StoryPort 或所需 LLM 时，这条链不是可用生产能力；部分只读 journal/chronicle API 仍可工作。

## worker 与生命周期

`LifeService` 是注册到 `SoulWorkers.life` 的 worker，处理 landmark/surprise/experience tick 等后台任务。Storyview 是另一个 `story-worker`，不属于 Life worker。

`LifeManager.stop()` 会停 LifeService；正常情况下由 `SoulService.stop()` 统一管理。

## 本地文件

Life/Presence 使用 `StorageConfig.life_dir`，典型文件包括：

- `experience_hot.jsonl`
- 虚拟与 anchor chronicle JSONL
- journal/agenda 状态
- `life_profile.json`
- `presence_state.json`

这些文件与 Memory/Accounts/Storyview 的 `.react/soul_db` JSON backend 是两套存储边界，不能混为同一个 backend。
