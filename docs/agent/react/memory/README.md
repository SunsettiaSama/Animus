# agent/react/memory

四层记忆系统，覆盖不同时间跨度与重要性的上下文保留需求，通过 `MemoryProcessor` 统一编排。

```
src/agent/react/memory/
├── memory.py               # Step + Memory（无界基础记录）
├── processor.py            # MemoryProcessor — 四层记忆统一入口
├── short_term/             # L1 短期记忆：Token 滑动窗口 + 蒸馏摘要
├── medium_term/            # L2 中期记忆：跨 session JSONL Q&A 历史 + 滚动整合
├── milestone/              # 里程碑记忆：LLM 评分，关键对话永久留存
└── long_term/              # L3 长期记忆：BGE Embedding + FAISS + RAG
    ├── memory.py
    ├── store.py
    ├── init/
    └── retrieve/
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

## 四层记忆对比

| 层级 | 实现类 | 存储位置 | 注入时机 | 保留内容 |
|---|---|---|---|---|
| L1 短期 | `ShortTermMemory` | 内存 | 每步 | 最近 N 步完整 Step |
| L1 蒸馏 | `ShortTermMemory._distillate` | 内存 | 窗口溢出时 LLM 更新 | 被驱逐步骤的 LLM 摘要 |
| L2 中期 | `RecentHistoryMemory` | JSONL 文件 | 每轮（跨 session 加载）| 最近 N 天的 Q&A 记录 |
| 里程碑 | `MilestoneMemory` | JSON 文件 | 每轮（关键词检索）| 评分达标的重要对话 |
| L3 长期 | `LongTermMemory` | FAISS + JSON | 每轮（语义检索）| 跨 session 向量化历史 |

## 统一入口：`MemoryProcessor`

```python
from config.agent.memory.memory_config import MemoryConfig
from agent.react.memory.processor import MemoryProcessor

processor = MemoryProcessor(cfg=MemoryConfig(), llm=llm)

# 每个推理步骤结束后调用
processor.add(step)

# 构建 Prompt 时调用；第 1+ 步复用 include_long_term=False 跳过向量检索
result = processor.recall(query="用户问题", include_long_term=True)

result.short_term             # list[Step]      — 当前窗口内完整步骤
result.short_term_distillate  # str             — 被驱逐步骤的蒸馏摘要
result.medium_term            # str             — 近期 Q&A 历史（已加载）
result.milestone              # str             — 里程碑检索结果
result.long_term              # str             — 向量检索结果

# 轮结束后落盘（后台线程中调用）
processor.commit(question, answer)
```

### `recall()` 的 `include_long_term` 参数

同一问题可能执行多步推理；向量检索（BGE + FAISS）只在第 0 步执行：

- **第 0 步**：`include_long_term=True`，执行向量检索 + 里程碑检索 + 加载 L2 中期历史
- **第 1+ 步**：`include_long_term=False`，复用缓存结果

## 数据流

```
用户提问
    │
    ▼
processor.recall(query, include_long_term=(i==0))
    ├─ short_term:            ShortTermMemory.steps()
    ├─ short_term_distillate: ShortTermMemory.distillate（溢出时由 LLM 更新）
    ├─ medium_term:           RecentHistoryMemory.render()（从 JSONL 加载）
    ├─ milestone:             MilestoneMemory.retrieve(query)
    └─ long_term:             LongTermMemory.smart_recall(query)（仅 i==0）

每步推理后：
processor.add(step)
    └─ ShortTermMemory.add(step)
            ├─ 未溢出 → 直接入队
            └─ 溢出   → 积累 pending，达 distill_trigger_steps 后 LLM 蒸馏

Action == "finish" → FinishEvent 后台线程：
processor.commit(question, answer)
    ├─ ShortTermMemory.flush()          ← 强制蒸馏剩余 pending 步骤
    ├─ RecentHistoryMemory.append()     ← 写入 JSONL；超限触发滚动整合
    ├─ LongTermMemory.add() + save()    ← 写入 FAISS + memories.json
    └─ MilestoneMemory.try_add()        ← LLM 评分达标则写入里程碑
            └─ evicted → LongTermMemory.add()  ← 溢出里程碑迁移至 L3
```

## 配置

顶层 `MemoryConfig` 聚合四层配置：

```python
from config.agent.memory.memory_config import MemoryConfig
cfg = MemoryConfig()
```

```yaml
# config/agent/memory.yaml 示例
short_term:
  enabled: true
  max_turns: 10
  max_tokens: 2048
  distill_enabled: true
  distill_trigger_steps: 4

medium_term:
  enabled: true
  window_days: 7
  max_entries: 30
  max_chars: 3000
  consolidate_enabled: true
  consolidate_batch: 10

milestone:
  enabled: true
  importance_threshold: 0.6
  top_k_retrieve: 2

long_term:
  enabled: true
  top_k: 5
  max_recall_chars: 3000
```

## 子模块文档

- [short_term](./short_term/README.md)
- [medium_term](./medium_term/README.md)
- [milestone](./milestone/README.md)
- [long_term](./long_term/README.md)
