# agent/react/memory/long_term

基于 BGE Embedding + FAISS 的长期记忆，以进程内向量库形式提供跨会话知识检索，支持持久化到磁盘。

```
src/agent/react/memory/long_term/
├── memory.py       # LongTermMemory — 薄封装，对外接口
├── store.py        # LongTermStore  — 向量库核心（嵌入 + 索引 + 持久化）
├── init/           # 工厂：make_memory / load_store / init_empty_store
└── retrieve/       # 检索器：Retriever + 四场景模式 + 自动触发
```

## 核心类：`LongTermStore`

```python
from config.agent.memory.memory_config import LongTermMemoryConfig
from agent.react.memory.long_term.store import LongTermStore, MemoryEntry

store = LongTermStore(entries=[], cfg=cfg)

# 新增条目后重建索引
store._entries.append(MemoryEntry.new("用户偏好：喜欢简短回答"))
store.rebuild_index()

# 按查询检索
text = store.recall("用户喜欢什么风格")

# 持久化
store.save()
```

### `MemoryEntry`

```python
@dataclass
class MemoryEntry:
    id: str           # UUID
    text: str         # 记忆正文
    created_at: str   # UTC ISO 时间戳
    meta: dict        # 任意附加信息
```

通过 `MemoryEntry.new(text, **meta)` 创建，自动填充 `id` 和 `created_at`。

### 持久化文件

| 文件 | 内容 |
|---|---|
| `memories.json` | 所有 `MemoryEntry` 的 JSON 序列化 |
| `memory_index.faiss` | FAISS 内积索引（已 L2 归一化，等价余弦相似度） |

### BGE 前缀规则

| 用途 | 配置项 | 默认值 |
|---|---|---|
| 检索 query | `query_prefix` | `"query: "` |
| 条目入库 | `passage_prefix` | `""` |

---

## 工厂函数（`long_term/init/`）

```python
from config.agent.memory.memory_config import LongTermMemoryConfig
from agent.react.memory.long_term import make_memory, load_store, init_empty_store

# 推荐：自动按配置决定是否从磁盘加载
memory = make_memory(cfg)

# 显式从磁盘加载（memories.json + memory_index.faiss）
store = load_store(cfg)

# 显式创建空库
store = init_empty_store(cfg)
```

`make_memory` 内部逻辑：`cfg.load_from_disk=True` → `load_store`，否则 → `init_empty_store`。

---

## 检索器（`long_term/retrieve/`）

### 四种检索场景

| 模式 | 触发条件 | 默认 top_k | 默认 min_score |
|---|---|---|---|
| `LIGHT` | 每轮推理前的基础检索 | 3 | 0.0 |
| `HEAVY` | query 含历史依赖关键词 | 8 | 0.5 |
| `SUPPLEMENT` | 短期+中期上下文过短 | 5 | 0.3 |
| `PROFILE` | 会话启动时检索用户档案 | 5 | 0.0 |

### `Retriever` 用法

```python
from config.agent.memory.retrieve_config import RetrieveConfig
from agent.react.memory.long_term.retrieve import Retriever, RetrieveRequest, RetrieveMode

retriever = Retriever(store=store, cfg=RetrieveConfig())

# 自动判断模式（推荐）
result = retriever.auto_retrieve(
    query="上次我们讨论的任务",
    is_session_start=False,
    short_term_context="...",
    medium_term_context="...",
)

result.hits      # list[str]，通过 min_score 过滤后的条目文本
result.combined  # str，条目以 "\n\n" 拼接，直接注入 Prompt
result.mode      # RetrieveMode，实际使用的模式
```

### 自动触发逻辑（`triggers.py`）

```
is_session_start=True         → PROFILE
query 含历史关键词             → HEAVY（"之前" / "上次" / "记得" / "earlier" 等）
短期+中期上下文长度 < min_len  → SUPPLEMENT
其他                          → LIGHT
```

---

## 配置：`LongTermMemoryConfig`

| 参数 | 默认值 | 说明 |
|---|---|---|
| `enabled` | `False` | 是否启用长期记忆 |
| `load_from_disk` | `False` | 启动时是否从 `memory_dir` 加载 |
| `memory_dir` | `""` | 持久化目录（由 `TaoConfig._propagate_dirs` 自动填充）|
| `top_k` | `5` | `store.recall()` 直接调用时的 top_k |
| `model_name_or_path` | `"BAAI/bge-small-zh-v1.5"` | BGE 模型路径或 HF id |
| `query_prefix` | `"query: "` | 检索前缀 |
| `passage_prefix` | `""` | 入库前缀 |
| `use_fp16` | `True` | 是否使用 FP16 |
| `device` | `"auto"` | `cuda` / `cpu` / `auto` |
| `retrieve` | `RetrieveConfig()` | 四场景检索参数 |
