# agent/soul/memory

Soul 侧记忆子系统：以 **统一记忆图**（MySQL 节点 + 边 + 可选 Qdrant 向量）为中心，分 **事件网络（event）** 与 **社交网络（social）** 两条子图；经 **I/O 边界** 与 Speak 会话、Life 体验对接。与 **`agent/react/context`**（会话 Step 轨迹 + 中期 JSONL）及按需 **`memory_recall`** 分工协作：**Prompt 默认只拼接会话上下文**，持久检索由工具或 Soul 服务完成。

源码：`src/agent/soul/memory/`。

---

## 顶层导出

```python
from agent.soul.memory import (
    MemoryService, MemoryBlock,
    MemoryRetriever, ScoredUnit,
    FactualMemory, ReconstructiveMemory, NarrativeMemory,
    NarrativeWriter, RuminationWriter,
)
```

入口 shim：`service.py` 将 `MemoryService.build` 绑定到 `facade/build.py` 的 `build_memory_service()`。

---

## 目录结构

```
src/agent/soul/memory/
├── service.py              # 向后兼容入口 → facade
├── unit.py                 # 向后兼容 re-export → graph.base_node + event node
├── retriever.py            # MemoryRetriever — 五种检索模式 + persona 聚类
├── embed_text.py           # 嵌入文本 / 余弦相似度 / cluster_key
├── emotion_intensity.py    # 节点情绪强度推断
│
├── facade/                 # L6 门面
│   ├── build.py            # build_memory_service() 工厂
│   ├── service.py          # MemoryService
│   ├── interactor_portrait.py
│   └── persona_context.py
│
├── io/                     # 对外 I/O 边界
│   ├── hub.py              # MemoryIO（session + life）
│   ├── session/            # Speak ↔ Memory 会话 I/O
│   └── life/               # Life ↔ Memory 体验 I/O
│
├── graph/                  # 记忆图核心
│   ├── base_node.py        # BaseNode（MemoryUnit 别名）
│   ├── node_store.py       # GraphNodeStore 协议
│   ├── query.py            # QueryEngine（事件网络检索）
│   ├── scored.py           # ScoredUnit
│   ├── traversal.py        # GraphTraversal（边 BFS）
│   ├── seeds.py            # SeedResolver（涌现种子）
│   ├── keywords.py
│   ├── cluster/            # ClusterIndex（语义聚类）
│   ├── node/
│   │   ├── create/         # 创建：archive / experience / compression / persist
│   │   ├── maintain/       # 维护：recall / forget / vectors
│   │   └── modify/         # 变更：evolve / merge / retract
│   └── networks/
│       ├── event/          # EventMemoryNetwork + 事件节点类型
│       ├── social/         # SocialMemoryNetwork + 社交节点类型
│       ├── store/          # MySQL 持久化 + codec
│       ├── writer/         # NarrativeWriter / RuminationWriter re-export
│       ├── semantic_index.py
│       ├── experience_block.py
│       └── block.py        # MemoryBlock（Prompt 渲染 DTO）
│
├── domain/                 # 共享域类型（Valence / MemoryTier / EdgeType …）
├── ports/                  # 跨模块 Protocol
├── emergence/              # 扩散激活 + Speak 点查询
├── rumination/             # 心跳反刍 + 重构写回
├── sleep/                  # 睡眠整合（forget / cluster rebuild）
└── processors/             # 邻域抽取（RuleNeighborhoodExtractor 等）
```

---

## 架构概览

### 双网络 + 统一存储

| 网络 | 模块 | 节点类型 | 职责 |
|---|---|---|---|
| **event** | `graph/networks/event/` | `FactualMemory` / `ReconstructiveMemory` / `NarrativeMemory` | 事实、重构、叙事记忆 |
| **social** | `graph/networks/social/` | `SocialCoreNode` / `SocialNeighborhoodNode` | 交互者画像、社交邻域 |

节点通过 `MySQLNodeStore` 写入表 `soul_memory_units`；边通过 `MySQLEdgeStore` 写入 `soul_memory_edges`。`MemoryTier.short_term` / `MemoryTier.long` 是节点字段，**不再分 Redis STM / MySQL LTM 两套存储**。

Schema：`graph/networks/store/mysql/schema.sql`（另含 `soul_interactors`、`soul_session_channels`）。

### I/O 边界：`MemoryIO`

```python
@dataclass(frozen=True)
class MemoryIO:
    session: SessionSpeakIO   # Speak ↔ Memory
    life: LifeMemoryIO        # Life ↔ Memory
```

`MemoryService` 暴露 `.io`、`.session_io`、`.life_io`、`.life_port`（→ `life.io.memory.LifeExperienceMemoryIO`）。

**Speak 会话 I/O（`io/session/`）**

| 入站 | 说明 |
|---|---|
| `submit_dialogue_turn` | 动态画像 + 涌现点事件 |
| `fetch_static_portrait` | 静态 SocialCore 画像 |
| `ingest_compression_block` | 对话压缩块 → `SessionMemoryBuffer`（会话内临时社交节点）|
| `close_session` | 缓冲清理 + 会话整合 |

**Life 体验 I/O（`io/life/`）**

```
ExperienceUnit
  → LifeExperienceMemoryIO.promote_unit()
  → LifeMemoryIO.submit_experience()（异步 enqueue）
  → LifeMemoryChannel.ingest_experience()
  → ExperienceGraphIngest.create_nodes()
  → ExperienceArchiver / SocialMemoryNetwork
  → RuminationService.observe_node()
```

`MemoryIngestMode` 仅保留 `formal`；会话闭合时 `close_dialogue_session` 只擢升终局 `ExperienceUnit`，不再合并 SessionMemoryBuffer。

---

## 记忆图流水线

### 创建（`node/create/`）

| 文件 | 职责 |
|---|---|
| `archive.py` | `ExperienceArchiver` — LLM 归档 ExperienceBlock → 图节点 |
| `experience.py` | `ExperienceGraphIngest` — 路由 event / social，正式落图 |
| `compression.py` | `DialogueCompressionBlock` → ExperienceUnit（Speak 压缩块）|
| `persist.py` | `NodePersister` — MySQL put + 向量 upsert |

### 维护（`node/maintain/`）

| 文件 | 职责 |
|---|---|
| `forget.py` | `NodeForgetEngine` — 低激活软删除 |
| `recall.py` | `record_recall_batch()` — 命中反馈 |
| `vectors.py` | 向量索引增删 |

### 变更（`node/modify/`）

| 文件 | 职责 |
|---|---|
| `evolve.py` | `CoreEvolver` — SocialCore 特质演化 |
| `merge.py` | `merge_neighborhood()` — 社交邻域去重 |
| `retract.py` | `retract_by_life_event()` — 按 life_event_id 归档 |

---

## 记忆单元

**基类：** `graph/base_node.py` — `BaseNode`

**事件网络**

| 类型 | `NODE_KIND` | 说明 |
|---|---|---|
| `FactualMemory` | `factual` | `fact` + `perception` |
| `ReconstructiveMemory` | `reconstructive` | `source_id`、`reconstructed_fact`、`trigger` |
| `NarrativeMemory` | `narrative` | `narrative`、`source_ids`、`chapter`；默认 `tier=long` |

**社交网络**

| 类型 | `NODE_KIND` | 说明 |
|---|---|---|
| `SocialCoreNode` | `social_core` | `portrait`、`agent_relation`、`trait_changelog` |
| `SocialNeighborhoodNode` | `social_neighborhood` | `label`、`content`、关联交互者 |

公共字段：`focus`、`emotion`、`emotion_intensity`、`valence`、`tier`、`base_activation`、`recall_count`、`last_accessed` 等。`activation(now, half_life_days)` 为运行时评分；`QueryEngine` 对 short_term / long 使用不同半衰期。

---

## `MemoryService`

工厂：

```python
MemoryService.build(
    llm,
    mysql_client,
    cfg=None,              # MemoryServiceConfig，默认读 config/soul/memory/service.yaml
    memory_infra=None,     # MemoryInfraService（Qdrant + embedder）
)
```

**无 `redis_client`**；向量经 `MemoryInfraService` + `SemanticVectorIndex` 接入。

### 写入与生命周期

| 方法 | 用途 |
|---|---|
| `life_port.promote_unit(unit)` | Life 体验正式落图（经 `io/life`）|
| `session_io.ingest_compression_block(...)` | Speak 压缩块 → 会话缓冲 |
| `ingest_heartbeat(...)` | 心跳重构 → `RuminationService` |
| `ingest_narrative` / `ingest_narrative_from_units` | 叙事编织 → `NarrativeMemory` |
| `forget_scan(threshold, dry_run)` | 事件 + 社交网络低激活软删除 |
| `run_sleep(...)` | 睡眠整合：forget、cluster rebuild、反刍缓冲 |
| `heartbeat_ruminate()` / `tick(snapshot)` | 心跳反刍调度 |

> **已移除：** `ingest_turn()`、`flush()`（原 STM→LTM 冲刷）、Redis `ShortTermMemoryManager`。

### 读取与涌现

| 方法 | 用途 |
|---|---|
| `recall(query, top_k, emotional_context)` | 事件网络混合检索 → `MemoryBlock` |
| `recall_social(query, top_k, interactor_id=...)` | 社交网络检索 |
| `search(mode, **kwargs)` | 五种模式 dict API（见下）|
| `activate_async(cue)` / `query_point_async(cue)` | 扩散激活 / Speak 点查询 |
| `request_speak_point_query(...)` | 对话轮触发涌现 |
| `get_activation_snapshot(session_id)` | 会话热激活快照 |

### 社交

| 方法 | 用途 |
|---|---|
| `register_core_portrait` / `register_external_visitor` | 注册 SocialCore |
| `evolve_core` / `set_agent_relation` | 画像演化 |
| `link_interactor_relation` | 交互者关系邻域 |
| `bind_session_channel` / `resolve_channel_interactor` | 会话 ↔ 交互者绑定 |

---

## `MemoryRetriever` 五种模式

均返回 `list[ScoredUnit]`（按 `final_score` 降序）。

1. **`recent`** — 按 `last_accessed` 近期条目。
2. **`semantic`** — 依赖 `SemanticVectorIndex`（Qdrant + embedder）。
3. **`by_valence`** — 按 `Valence` 过滤，可选情绪提示。
4. **`by_field`** — 结构化 AND 条件（类型、章节、`source_id`、时间范围等）。
5. **`hybrid`** — `w_relevance × relevance + w_activation × activation`；无向量时降级。

另含 persona 聚类分析：`persona_clusters`、`fetch_persona_cluster`。

---

## 子系统

### Emergence（`emergence/`）

扩散激活：`SpreadActivationService` 从 cluster 种子 + 图 BFS 传播；`SpeakEmergence` 包装 Speak 点查询；`EmergenceQueryDispatcher` 线程池异步调度。

### Rumination（`rumination/`）

`RuminationService` 观察高情绪节点 → 缓冲 → 心跳 `ruminate()` → `RuminationWriter` LLM 重构写回 + 建边。

### Sleep（`sleep/`）

`SleepService.run()`：forget scan、cluster rebuild、反刍缓冲投喂、缓冲衰减。

---

## 存储与配置

| 存储 | 说明 |
|---|---|
| **MySQL** | `soul_memory_units`、`soul_memory_edges`、`soul_interactors`、`soul_session_channels` |
| **Qdrant**（可选）| `MemoryInfraService` + `SemanticVectorIndex` |
| **会话缓冲** | `SessionMemoryBuffer` — 会话内临时社交节点（`meta.session_buffer=True`）|
| **涌现快照** | 进程内 `snapshot_store` / `point_store` |

| 文件 | 说明 |
|---|---|
| `config/soul/memory/service.yaml` | 半衰期、recall_top_k、forget_threshold、cluster、activation、async_ingest 等 |
| `config/infra/db.yaml` | `MySQLConfig`（Soul 记忆仅需 MySQL；Redis 仍可用于其它组件）|

配置类：`config/soul/memory/service_config.py` → `MemoryServiceConfig`。

---

## 与 React 记忆的关系

| | React `MemoryProcessor`（`context/`） | Soul `MemoryService` |
|---|---|---|
| 典型用途 | 本会话 Step + 中期 JSONL | 跨会话记忆图（event + social）|
| 后端 | 内存 trace + `medium_term.jsonl` | MySQL（+ 可选 Qdrant）|
| 写入路径 | `processor.commit()` | Life `promote_unit` / Speak 压缩块 / 心跳反刍 |
| 单元模型 | `Step` + 摘要条目 | `BaseNode` + activation + 图边 |

按需 **`memory_recall`** 读取 Soul 图或 legacy 向量 / 里程碑后端；旧 **`agent/react/memory/`** 源码树已移除。

---

## 相关文档

- [life/README.md](../life/README.md)（体验擢升 → `life.io.memory`）
- [speak/README.md](../speak/README.md)（recall handoff、压缩块、涌现回调）
- [heartbeat/README.md](../heartbeat/README.md)（反刍 / wander / sleep tick）
- [agent/soul/README.md](../README.md)（SoulService 总览）
