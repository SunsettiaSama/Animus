# agent/soul/memory

Memory 是事件与社交两张逻辑网络共享的记忆图，支持 MySQL 和本地 JSON 两种持久化后端；向量检索是可选增强。另有一条与双网完全隔离的增量式 stack 旁路基座（`bypass/`），对外与主图讲同一套检索协议（`ports.MemoryBasePort`：`ingest / recall / search`），可整座替换用于对比实验（见 `src/evals/memory_humaneness/`）。

## 结构

```text
src/agent/soul/memory/
├── facade/                     MemoryService 工厂与门面
├── graph/
│   ├── node/create|maintain|modify/
│   ├── networks/event/
│   ├── networks/social/
│   └── networks/store/
│       ├── mysql/
│       └── json/
├── bypass/                     增量式 stack 旁路基座（与 event/social 隔离）
├── io/session/                 Speak 会话、画像、压缩块
├── io/life/                    Life 体验擢升
├── emergence/                  扩散激活与点查询
├── rumination/
├── sleep/
├── ports/                      store / 向量 / 检索协议（含 MemoryBasePort）
└── retriever.py
```

兼容入口 `memory/service.py` 仍把 `MemoryService.build` 指向 `facade/build.py`，但实际实现应从 facade 和 graph 目录理解。

## 双网络

| 网络 | 主要节点 | 用途 |
|---|---|---|
| event | `FactualMemory`、`ReconstructiveMemory`、`NarrativeMemory` | 事实、重构、叙事 |
| social | `SocialCoreNode`、`SocialNeighborhoodNode` | 交互者画像与关系邻域 |

两张网络共享 node/edge store；`MemoryTier` 是节点字段，不存在 Redis STM → MySQL LTM 的双库迁移。

## 后端选择

`build_memory_service(..., storage_backend, json_root)`：

### MySQL

- 要求非空 `mysql_client`，否则抛 `RuntimeError`。
- node、edge、interactor、session-channel 使用 `graph/networks/store/mysql/`。
- 主要表为 `soul_memory_units`、`soul_memory_edges`、`soul_interactors`、`soul_session_channels`。
- `MemoryInfraService.build()` 可接 embedding/Qdrant；是否启用由 infra 配置决定。

### JSON

- 使用 `JsonStorageService(json_root)`，默认 `.react/soul_db`。
- collections 包括 `memory/nodes`、edges、interactors 和 session channels。
- 工厂默认构造 `enabled=False` 的 `MemoryInfraService`，因此没有默认向量索引；semantic/hybrid 能力会缺少向量增强。
- JSON 是单机本地 fallback，没有 MySQL 的事务、跨进程锁和部署语义，不应宣称为生产级共享存储。

### `auto`

`SoulService` 不把 `auto` 直接传入 Memory，而是先通过 `DBConfig.resolved_storage_backend()` 解析：显式 mysql/json 优先；MySQL 禁用或探测不可达时选 JSON。

同一解析结果也会用于 Accounts 与 Storyview，避免三个子系统混用不同后端。

## 创建与检索

写入主路径：

```text
Life ExperienceUnit
  → LifeExperienceMemoryIO
  → Memory LifeMemoryIO
  → ExperienceGraphIngest
  → event/social network
  → node/edge store
  → 可选 vector upsert
```

Speak 压缩块先进入 Life 的体验编写流程，再作为正式 ExperienceUnit 落图；session buffer 仍用于会话期画像/社交上下文。

读取能力：

- `recall()`：事件网络混合检索。
- `recall_social()`：社交网络检索。
- `search()`：recent、semantic、by_valence、by_field、hybrid。
- `activate_async()` / `query_point_async()`：扩散激活。
- persona drift units：供 Persona monthly drift。

semantic 模式需要可用 embedding/vector backend；在 JSON 默认配置下不能把它描述成保证可用。

## 生命周期与 worker

`SoulService.start()` 会：

1. 构造 `MemoryHandler/MemoryService`。
2. 调用 `init_infra()`。
3. 预热 hot spread。
4. 把 Memory 的后台写入绑定到 `SoulWorkers.memory`。
5. 接线 Speak session callbacks、Life memory port 和 Persona drift port。

`run_wander()`、sleep、部分写入在 memory worker 上串行。`SoulService.stop()` 在停 worker 前执行 shutdown memory sleep。

## 子系统

- Emergence：cluster seed + graph traversal 的扩散激活。
- Rumination：观察高情绪节点，心跳时重构并建边。
- Sleep：forget、cluster rebuild、rumination buffer 处理。
- Session I/O：动态/静态交互者画像、keyword/point query、channel binding。

## 与 React context 的边界

`agent/react/context` 是当前会话 Step 与中期 JSONL；Soul Memory 是跨会话记忆图。Prompt 不会因为 Memory 已持久化就自动拥有全部长期记忆，仍需 Speak handoff、compose injection 或 Tao recall 工具接入。
