# react/memory

四级记忆系统，覆盖不同时间跨度与重要性的上下文保留需求，通过 `MemoryProcessor` 统一编排。

```
memory/
├── memory.py               # Step + Memory（无界基础记录）
├── processor.py            # MemoryProcessor — 四级记忆统一入口
├── short_term/             # 短期记忆：Token 滑动窗口
├── medium_term/            # 中期记忆：知识蒸馏（Rolling Distillate）
├── milestone/              # 里程碑记忆：LLM 评分，关键对话永久留存
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

## 四级记忆对比

| 层级 | 实现 | Token 占用 | 保留内容 |
|---|---|---|---|
| 短期 | 滑动窗口 | ≤ `max_tokens` | 最近 N 轮完整 Step |
| 中期 | 滚动蒸馏 | 固定 ≤ `max_distillate_tokens` | 历史推理主线提炼 |
| 里程碑 | LLM 重要性评分 + 关键词检索 | 按需检索，不占固定空间 | 用户关键事件 / 重要决策 |
| 长期 | BGE + FAISS + RAG | 按需检索，不占固定空间 | 跨会话持久知识 |

## 统一入口：`MemoryProcessor`

```python
from config.react.memory.memory_config import MemoryConfig
from react.memory import MemoryProcessor

processor = MemoryProcessor(cfg=MemoryConfig(), llm=llm)

# 每个推理步骤结束后调用
processor.add(step)

# 构建 Prompt 时调用
# include_long_term=False 跳过向量检索，适用于同一问题的第 2+ 步
result = processor.recall(query="用户问题", include_long_term=True)
result.short_term   # list[Step]，注入完整对话历史
result.medium_term  # str，注入蒸馏摘要
result.long_term    # str，注入向量检索结果（include_long_term=False 时为 ""）
result.milestone    # str，注入里程碑记忆（无匹配时为 ""）

# 读取当前中期蒸馏文本（post_process 时用于构建静态 Prompt 缓存）
processor.medium_distillate  # str
```

### `recall()` 的 `include_long_term` 参数

ReAct 链中同一问题可能执行多步推理。长期向量检索（BGE Embedding + FAISS）是相对耗时的操作，而检索结果在同一问题的多步推理中不会变化，因此：

- **第 0 步**：`include_long_term=True`，执行完整检索，缓存结果到局部变量 `_cached_lt`
- **第 1+ 步**：`include_long_term=False`，跳过检索，直接复用 `_cached_lt`

`MemoryProcessor` 内部的 `_is_session_start` 标志仅在 `include_long_term=True` 且实际调用 `smart_recall` 时更新，不受后续步骤影响。

里程碑检索在每次 `recall()` 中均执行（无需跳过），因为其检索基于关键词匹配，开销极低。

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
                            ├─ pending < distill_trigger_steps → 暂存
                            └─ pending >= distill_trigger_steps → LLM 蒸馏（覆盖旧蒸馏文本）
```

## commit() 与 post_process() 的关系

`commit()` 由 `TaoLoop.post_process()` 在后台线程中调用（FinishEvent 发送给客户端后）：

```
post_process() [后台线程]
  └─ processor.commit(question, answer)
        ├─ medium.flush()                    ← 强制蒸馏剩余 pending steps
        ├─ long.add(...) + long.save()       ← 写入 FAISS + memories.json
        └─ milestone.try_add(...)            ← LLM 评分，达标则写入里程碑
              └─ evicted → long.add(...)     ← 溢出里程碑迁移至 L3，防止丢失
```

commit 结束后，`post_process()` 通过 `processor.medium_distillate` 读取最新蒸馏文本，用于构建下一轮的静态 Prompt 缓存（`StaticPromptParts`）。

## 配置

顶层配置类 `MemoryConfig` 聚合四层配置，支持字典或 YAML 构造：

```python
from config.react.memory.memory_config import MemoryConfig

# 从 YAML 加载
cfg = MemoryConfig.from_yaml("config/memory.yaml")

# 从字典构造
cfg = MemoryConfig.from_dict({
    "short_term":  {"enabled": True, "max_turns": 10, "max_tokens": 2048},
    "medium_term": {"enabled": True, "distill_trigger_steps": 4, "max_distillate_tokens": 400},
    "milestone": {
        "enabled": True,
        "milestone_dir": ".react/milestones",
        "importance_threshold": 0.6,
        "top_k_retrieve": 2,
    },
    "long_term": {
        "enabled": True,
        "load_from_disk": True,
        "memory_dir": ".react/memory",
        "model_name_or_path": "BAAI/bge-small-zh-v1.5",
        "retrieve": {"heavy_top_k": 8, "heavy_min_score": 0.5},
    },
})
```

## 子模块文档

- [short_term](./short_term/README.md)
- [medium_term](./medium_term/README.md)
- [milestone](./milestone/README.md)
- [long_term](./long_term/README.md)
