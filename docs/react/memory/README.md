# react/memory

三级记忆系统，覆盖不同时间跨度的上下文保留需求，通过 `MemoryProcessor` 统一编排。

```
memory/
├── memory.py               # Step + Memory（无界基础记录）
├── processor.py            # MemoryProcessor — 三级记忆统一入口
├── short_term/             # 短期记忆：Token 滑动窗口
├── medium_term/            # 中期记忆：滚动摘要
└── long_term/              # 长期记忆：BGE Embedding + FAISS + RAG
    ├── memory.py           # LongTermMemory（薄封装）
    ├── store.py            # LongTermStore（向量库 + 持久化）
    ├── init/               # 工厂函数：make_memory / load_store
    └── retrieve/           # 检索器：Retriever + 四场景 + 自动触发
```

## 数据单元：`Step`

```python
@dataclass
class Step:
    thought: str         # LLM 推理过程
    action: str          # 动作名称
    action_input: dict   # 动作参数
    observation: str     # 工具返回结果
```

## 三级记忆对比

| 层级 | 实现 | Token 占用 | 保留内容 |
|---|---|---|---|
| 短期 | 滑动窗口 | ≤ `max_tokens` | 最近 N 轮完整 Step |
| 中期 | 滚动摘要 | 固定 ≤ `max_summary_tokens` | 历史推理主线摘要 |
| 长期 | BGE + FAISS + RAG | 按需检索，不占固定空间 | 跨会话持久知识 |

## 统一入口：`MemoryProcessor`

```python
from config.react.memory.memory_config import MemoryConfig
from react.memory import MemoryProcessor

processor = MemoryProcessor(cfg=MemoryConfig(), llm=llm)

# 每个推理步骤结束后调用
processor.add(step)

# 构建 Prompt 时调用
result = processor.recall(query="用户问题")
result.short_term   # list[Step]，注入完整对话历史
result.medium_term  # str，注入摘要
result.long_term    # str，注入检索结果
```

`MemoryProcessor` 内部自动处理驱逐链（短期 → 中期），`recall()` 对长期记忆执行向量检索。

## 数据流

```
Step 产生
    │
    ▼
MemoryProcessor.add(step)
    │
    ▼
ShortTermMemory.add(step)  →  evicted: list[Step]
    │
    ├─ evicted 为空 → 结束
    └─ evicted 非空 → MediumTermMemory.absorb(evicted)
                            │
                            ├─ pending < trigger_steps → 暂存
                            └─ pending >= trigger_steps → LLM 生成摘要（覆盖旧摘要）
```

## 配置

顶层配置类 `MemoryConfig` 聚合三层配置，支持字典或 YAML 构造：

```python
from config.react.memory.memory_config import MemoryConfig

# 从 YAML 加载
cfg = MemoryConfig.from_yaml("config/memory.yaml")

# 从字典构造
cfg = MemoryConfig.from_dict({
    "short_term":  {"enabled": True, "max_turns": 10, "max_tokens": 2048},
    "medium_term": {"enabled": True, "summary_trigger_steps": 4, "max_summary_tokens": 400},
    "long_term":   {
        "enabled": True,
        "load_from_disk": True,
        "memory_dir": "long_term_memory",
        "model_name_or_path": "BAAI/bge-small-zh-v1.5",
        "retrieve": {"heavy_top_k": 8, "heavy_min_score": 0.5},
    },
})
```

## 子模块文档

- [short_term](./short_term/README.md)
- [medium_term](./medium_term/README.md)
- [long_term](./long_term/README.md)
