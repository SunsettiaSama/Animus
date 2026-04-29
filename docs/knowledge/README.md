# Knowledge Base

知识库模块（`src/knowledge/`）提供结构化的文档存储、向量化检索与缓存能力，供 Agent 工具和 WebUI 调用。

---

## 架构概览

```
KnowledgeBase (facade)
  ├── KnowledgeStore        — MySQL：文档元数据、原文 blob、分块
  ├── KnowledgeVectorStore  — Qdrant：向量索引（本地文件）
  ├── KnowledgeCache        — Redis：查询缓存、chunk 缓存、版本控制
  ├── KnowledgeEmbedder     — HuggingFace BGE 嵌入模型（懒加载、线程安全）
  ├── KnowledgeIngestion    — 写入：分块 → 嵌入 → MySQL + Qdrant
  └── KnowledgeRetriever    — 读取：keyword / semantic / hybrid 三种模式
```

数据流：

```
ingest_text(text)
  └─ _chunk_text()                   # 按 chunk_size / overlap 分块
      ├─ KnowledgeStore.insert_chunks()   # 写 MySQL doc_chunks
      ├─ KnowledgeEmbedder.embed_documents()  # BGE 向量化
      ├─ KnowledgeVectorStore.upsert()    # 写 Qdrant
      └─ KnowledgeCache.incr_version()   # 使旧查询缓存失效

search_hybrid(query)
  ├─ KnowledgeCache.get_query()      # 命中则直接返回
  ├─ [keyword]  KnowledgeStore.fulltext_search()
  ├─ [semantic] KnowledgeVectorStore.search() → KnowledgeStore.get_chunks_by_ids()
  └─ KnowledgeCache.set_query()      # 写缓存
```

---

## MySQL Schema

文件：[`src/knowledge/schema.sql`](../../src/knowledge/schema.sql)

### `documents`

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | VARCHAR(36) | UUID 主键 |
| `source` | VARCHAR(512) | 来源路径或标识 |
| `source_type` | VARCHAR(32) | `text` / `file` 等 |
| `title` | VARCHAR(512) | 可选标题 |
| `status` | VARCHAR(32) | `pending` / `indexed` / `failed` |
| `meta` | JSON | 任意扩展字段（domain、concept 等） |
| `created_at` / `updated_at` / `deleted_at` | DATETIME | 时间戳，软删除 |

索引：`idx_doc_status`、`idx_doc_deleted`

### `content_blobs`

存储文档原始全文（可选写入，`store_blob=True` 时使用）。

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | VARCHAR(36) | UUID 主键 |
| `doc_id` | VARCHAR(36) | FK → `documents.id` |
| `content` | LONGTEXT | 文档全文 |
| `encoding` | VARCHAR(32) | 默认 `utf-8` |

### `doc_chunks`

文档分块，支持全文索引检索。

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | VARCHAR(36) | UUID 主键 |
| `doc_id` | VARCHAR(36) | FK → `documents.id` |
| `chunk_index` | INT | 块序号（从 0 开始） |
| `content` | TEXT | 块内容 |
| `is_indexed` | BOOLEAN | 是否已向量化写入 Qdrant |
| `meta` | JSON | 继承自文档的扩展字段 |

索引：`idx_chunk_doc`、`idx_chunk_indexed`、`FULLTEXT ft_chunk_content(content)`

---

## Redis 缓存设计

实现：[`src/knowledge/cache.py`](../../src/knowledge/cache.py)

| Key 格式 | 用途 | TTL |
|---|---|---|
| `kb:index:version` | 全局索引版本号（写入时递增） | 永久 |
| `kb:domain:{domain}:version` | 领域级版本号 | 永久 |
| `kb:q:{hash16}` | 查询结果缓存，hash = SHA256(mode:top_k:query)[:16] | `cache_ttl ± 20%` |
| `kb:chunk:{id}` | chunk 原文内容（减少 MySQL 重复查询） | `600s ± 20%` |
| `kb:doc:{id}:status` | 文档写入状态 | `60s ± 20%` |

**版本控制**：每次写入文档调用 `incr_version(domain)`，查询时对比缓存中存储的版本号与当前版本号，不一致则视为缓存失效。`get_version(domain)` 返回 `max(global_v, domain_v)`，确保全局写入也能使领域缓存失效。

**TTL 抖动**：所有有过期时间的 key 使用 `_jitter(base, pct=0.2)` 添加 ±20% 随机偏移，防止大量 key 同时过期引发缓存雪崩。

---

## Qdrant 向量存储

实现：[`src/knowledge/vector_store.py`](../../src/knowledge/vector_store.py)

- 本地文件模式：`QdrantClient(path=cfg.qdrant_path)`，默认路径 `.react/knowledge_base/qdrant`
- 向量维度自动推断：模型名含 `large` → 1024，含 `base` → 768，其余默认 512
- 相似度：余弦（Cosine）
- Payload 存储：每个向量点存储 `doc_id`、`chunk_index`、`content`（截断到 2048 字符）、`meta`
- `search(vector, top_k, filter)` 支持按 `doc_id` 过滤

---

## KnowledgeEmbedder

实现：[`src/knowledge/embedder.py`](../../src/knowledge/embedder.py)

默认模型：`BAAI/bge-small-zh-v1.5`，支持 `device="auto"`（自动选 CUDA/CPU）、FP16 量化。

懒加载 + `threading.Lock` 保证多线程环境下只初始化一次。由 `KnowledgeBase.from_config()` 创建单例，同时注入 `KnowledgeIngestion` 和 `KnowledgeRetriever`，避免重复加载模型。

```python
embedder = KnowledgeEmbedder(cfg)
embedder.embed_query("量子纠缠")          # -> list[float]
embedder.embed_documents(["chunk1", ...]) # -> list[list[float]]
```

---

## 检索模式

实现：[`src/knowledge/retriever.py`](../../src/knowledge/retriever.py)

### `search_keyword(query, top_k, domain=None)`

1. 检查 Redis 查询缓存（`mode="keyword"`）
2. 未命中 → MySQL `FULLTEXT` 全文搜索（`ft_chunk_content`）
3. 结果写入 Redis 查询缓存

### `search_semantic(query, top_k, doc_id_filter=None, domain=None)`

1. 检查 Redis 查询缓存（`mode="semantic"`）
2. 未命中 → `KnowledgeEmbedder.embed_query()` → Qdrant 向量检索
3. 补全内容：优先从 `Redis chunk 缓存`读取，缺失时查 MySQL 并回写缓存
4. 结果写入 Redis 查询缓存

### `search_hybrid(query, top_k_each=3, doc_id_filter=None, domain=None)`

1. 检查 Redis 查询缓存（`mode="hybrid"`）
2. 未命中 → `ThreadPoolExecutor` 并行执行 `search_keyword` 和 `search_semantic`（各取 `top_k_each` 条）
3. 去重合并：语义结果优先，keyword 结果补充（按 `chunk_id` 去重）
4. 结果写入 Redis 查询缓存

`search(query, top_k)` 为向后兼容入口，等价于 `search_semantic`，降级链：Redis → Qdrant Payload → MySQL → FTS。

---

## KnowledgeBase Facade

实现：[`src/knowledge/__init__.py`](../../src/knowledge/__init__.py)

外部只需使用 `KnowledgeBase`，无需直接操作子组件：

```python
from config.knowledge.config import KnowledgeConfig
from knowledge import KnowledgeBase

cfg = KnowledgeConfig.from_yaml("config/knowledge.yaml")
kb = KnowledgeBase.from_config(cfg)
kb.setup()  # 建表 + 确保 Qdrant collection

doc_id = kb.ingest_text("量子计算是...", title="量子基础", meta={"domain": "physics"})

results = kb.hybrid_search("量子纠缠", top_k_each=3)
for r in results:
    print(r.score, r.content[:80])
```

公共方法：

| 方法 | 说明 |
|---|---|
| `setup()` | 初始化 MySQL 表结构 + Qdrant collection |
| `ingest_text(text, ...)` | 写入文本，返回 `doc_id` |
| `ingest_file(path, ...)` | 读取文件并写入 |
| `delete(doc_id)` | 软删除文档（MySQL + Qdrant） |
| `search(query, top_k)` | 语义检索（向后兼容） |
| `search_keyword(query, top_k)` | 关键词全文检索 |
| `search_semantic(query, top_k)` | 语义向量检索 |
| `hybrid_search(query, top_k_each)` | 混合并行检索 |
| `repair()` | 修复未向量化的 chunks |
| `rebuild()` | 全量重建向量索引 |

---

## KnowledgeConfig

文件：[`src/config/knowledge/config.py`](../../src/config/knowledge/config.py)

| 字段 | 默认值 | 说明 |
|---|---|---|
| `mysql_url` | `mysql+pymysql://root:password@localhost:3306/knowledge` | MySQL 连接串 |
| `redis_url` | `redis://localhost:6379/0` | Redis 连接串 |
| `qdrant_path` | `.react/knowledge_base/qdrant` | Qdrant 本地文件路径 |
| `collection_name` | `knowledge` | Qdrant collection 名称 |
| `embedding_model` | `BAAI/bge-small-zh-v1.5` | HuggingFace 模型 ID |
| `device` | `auto` | `auto` / `cuda` / `cpu` |
| `passage_prefix` | `""` | 文档向量化前缀（BGE 专用） |
| `query_prefix` | `"query: "` | 查询向量化前缀 |
| `use_fp16` | `True` | GPU 时使用 FP16 |
| `batch_size` | `32` | 向量化批大小 |
| `top_k` | `5` | 默认检索条数 |
| `cache_ttl` | `300` | Redis 查询缓存 TTL（秒） |
| `chunk_size` | `512` | 分块字符数 |
| `chunk_overlap` | `64` | 分块重叠字符数 |

加载方式：`KnowledgeConfig.from_yaml(path)` 或 `KnowledgeConfig.from_dict(d)`

---

## Docker 依赖

知识库功能需要 MySQL 和 Redis，通过 Docker Compose 启动：

```bash
docker compose -f docker/docker-compose-db.yml up -d
```

容器名：`react-mysql`（端口 3306）、`react-redis`（端口 6379）。
