# agent/soul/memory

Soul 侧记忆子系统：以 **Redis 短期记忆（STM）** 与 **MySQL 长期记忆（LTM）** 为中心，配合 LLM 提炼 / 心跳重构 / 叙事编织写入，以及可选向量后端的混合检索。与 **`agent/react/context`**（会话 Step 轨迹 + `RecentHistoryMemory`）及按需 **`memory_recall`**（可挂载 legacy Qdrant / 里程碑或 Soul 后端）分工协作：**Prompt 默认只拼接会话上下文**，持久检索由工具或 Soul 服务完成。

---

## 目录结构（核心路径）

```
src/agent/soul/memory/
├── unit.py              # MemoryUnit 抽象 + Factual / Reconstructive / Narrative
├── codec.py             # dict / JSON 序列化与反序列化
├── service.py           # MemoryService — 对外统一入口 + MemoryBlock 渲染
├── retriever.py         # MemoryRetriever — recent / semantic / valence / field / hybrid
├── flush.py             # FlushEngine — STM → LTM 批量归档
├── short_term/
│   └── manager.py       # ShortTermMemoryManager（Redis，TTL ∝ activation）
├── long_term/
│   ├── schema.sql       # MySQL 表 soul_memory_units
│   └── manager.py       # LongTermMemoryManager（CRUD、forget_scan、命中反馈）
└── writer/
    ├── turn_writer.py       # TurnWriter — 轮末提炼 → FactualMemory → STM（高情绪可直写 LTM）
    ├── heartbeat_writer.py   # HeartbeatWriter — 事实 → ReconstructiveMemory → LTM
    └── narrative_writer.py   # NarrativeWriter — 多条 unit → NarrativeMemory → LTM
```

同级还存在 `milestone/`、`long_term/memory.py`、`long_term/store.py`、`long_term/retrieve/` 等扩展路径，供里程碑与既有 LTM 检索分发复用；新接入优先通过 `MemoryService` / `MemoryRetriever`。

---

## 记忆单元：`MemoryUnit`

| 类型 | `MEMORY_TYPE` | 含义 |
|---|---|---|
| `FactualMemory` | `factual` | 客观 `fact` + 主观 `perception`，默认落在 STM |
| `ReconstructiveMemory` | `reconstructive` | 指向 `source_id`（源事实 id），`reconstructed_fact` + `trigger` |
| `NarrativeMemory` | `narrative` | `narrative` 段落 + `source_ids` + `chapter`，初始化即 `tier=long` |

公共字段包括：`focus`、`emotion`、`emotion_intensity`、`valence`（`Valence` 枚举）、`base_activation`、`recall_count`、`last_accessed` 等。`activation(now, half_life_days)` 为运行时评分（衰减 + 召回提升 + 情绪加成），STM / LTM 使用各自配置的半衰期。

---

## `MemoryService`

工厂：`MemoryService.build(llm, redis_client, mysql_client, cfg=None, embedder=None, vector_store=None)`。

- **`cfg`**：未传时读取 `config/soul/memory/service.yaml`，不存在则用默认值。
- **`embedder` / `vector_store`**：满足 `EmbedderBackend.embed()`、`VectorBackend.search()` 协议时可启用语义检索；否则 `hybrid` 等模式降级为近期 + activation。

### 写入

| 方法 | 用途 |
|---|---|
| `ingest_turn(question, answer, persona_snapshot)` | 轮末写入；默认后台线程（`async_ingest`） |
| `ingest_heartbeat(source_unit_id, trigger, emotional_context)` | 心跳重构 → `ReconstructiveMemory` |
| `ingest_narrative` / `ingest_narrative_from_units` | 日终或回顾 → `NarrativeMemory` |

### 生命周期

| 方法 | 用途 |
|---|---|
| `flush()` | STM 中 activation ≥ floor 的条目写入 LTM 并从 Redis 删除 |
| `forget_scan(threshold, dry_run)` | LTM 低激活软删除（与 `ltm_half_life_days` 等配合） |

### 读取

| 方法 | 用途 |
|---|---|
| `recall(query, top_k, emotional_context)` | 混合打分检索 → `MemoryBlock.render()` 注入 Prompt；并对 STM/LTM 触发命中反馈 |
| `retriever` | 暴露 `MemoryRetriever`，可使用五种检索模式组合 |

---

## `MemoryRetriever` 五种模式

均返回 `list[ScoredUnit]`（按 `final_score` 降序）。

1. **`recent`** — 按 `last_accessed` 近期条目，可跨 STM/LTM。
2. **`semantic`** — 依赖 `embedder` + `vector_store`。
3. **`by_valence`** — 按 `Valence` 过滤，可选情绪提示。
4. **`by_field`** — 结构化 AND 条件（类型、章节、`source_id`、时间范围等）。
5. **`hybrid`** — `w_relevance × relevance + w_activation × activation`；无嵌入后端时降级。

---

## 存储与运维

- **Redis**：键前缀 `soul:stm:`，单元 JSON + 按 `valence` / `memory_type` 的索引集合；TTL ≈ `half_life_days × activation`（下限 `min_ttl_hours`）。
- **MySQL**：执行 `long_term/schema.sql` 初始化表 `soul_memory_units`；DSN 见 `config/infra/db.yaml`。

---

## 配置

| 文件 | 说明 |
|---|---|
| `config/soul/memory/service.yaml` | STM/LTM 半衰期、`promote_threshold`、`recall_top_k`、`flush_activation_floor`、`async_ingest` 等 |
| `config/infra/db.yaml` | `RedisConfig` + `MySQLConfig`，对应 `DBConfig.load_default()` |

配置类：`config/soul/memory/service_config.py` 的 `MemoryServiceConfig`，`config/infra/db_config.py` 的 `DBConfig`。

`TaoConfig`（`config/agent/tao_config.py`）含可选字段 **`db: DBConfig | None`**，用于在上层组装 Soul 所需客户端时与 Agent 配置对齐。

---

## 与 React 记忆的关系（简述）

| | React `MemoryProcessor`（`context/`） | Soul `MemoryService` |
|---|---|---|
| 典型用途 | 本会话 Step + 中期 JSONL | 跨会话 STM/LTM 单元 |
| 后端 | 内存 trace + `medium_term.jsonl` | Redis + MySQL（+ 可选向量）|
| 单元模型 | `Step` + 摘要条目 | `MemoryUnit` + activation |

按需 **`memory_recall`** 读取 **`agent/soul/memory`** 中的向量层 / 里程碑或 Soul 后端；旧 **`agent/react/memory/`** 源码树已移除。
