# react/memory/milestone

里程碑记忆，介于中期蒸馏与长期向量库之间的第三层持久化存储。通过 LLM 对每次对话进行重要性评分，仅将达到阈值的关键事件写入结构化条目，并在下次相关问题出现时按需注入 Prompt。

```
milestone/
├── entry.py      # MilestoneEntry — 单条里程碑数据结构
├── store.py      # MilestoneStore — 内存管理 + JSON 持久化
├── scorer.py     # ImportanceScorer — LLM 评分 + 条目构建
├── retriever.py  # MilestoneRetriever — 关键词检索
├── memory.py     # MilestoneMemory — 对外统一接口
└── init.py       # make_milestone() — 工厂函数
```

## 数据单元：`MilestoneEntry`

```python
@dataclass
class MilestoneEntry:
    id: str           # UUID
    summary: str      # 一句话概括（≤ max_summary_chars 字符）
    detail: str       # 完整 Q&A 原文（≤ max_detail_chars 字符）
    created_at: str   # UTC ISO 时间戳
    keywords: list[str]  # LLM 提取的关键词（≤ max_keywords 个）
    emotion: str      # "positive" | "negative" | "neutral"
    importance: float # LLM 给出的重要性评分（0.0–1.0）
```

通过 `MilestoneEntry.new(summary, detail, keywords, emotion, importance)` 创建，自动填充 `id` 和 `created_at`。

## 核心类：`MilestoneMemory`

```python
from config.react.memory.milestone_config import MilestoneConfig
from react.memory.milestone import make_milestone

cfg = MilestoneConfig(enabled=True, importance_threshold=0.6)
milestone = make_milestone(cfg, llm=llm)

# commit() 中调用，评分并按需写入
added, evicted = milestone.try_add(question, answer, steps)
if added:
    milestone.save()
# evicted：因容量溢出被驱逐的低分条目，调用方应迁移到 L3

# recall() 中调用，关键词检索并格式化为 Prompt 文本
text = milestone.retrieve(query)  # 无匹配时返回 ""
```

## 工厂函数：`make_milestone`

```python
from react.memory.milestone.init import make_milestone

# cfg.enabled=True  → 从 milestone_dir/milestones.json 加载已有条目
# cfg.enabled=False → 创建空 store（不读盘，不写盘）
milestone = make_milestone(cfg, llm=llm)
```

## 重要性评分：`ImportanceScorer`

每次 `commit()` 后，`ImportanceScorer` 向 LLM 发送如下结构化 Prompt，要求输出 JSON：

```
你是一个对话重要性评估器。请判断以下对话是否值得作为长期里程碑记录下来。

评估标准（以下任意一条符合即可视为重要）：
- 用户分享了重要个人事件（情感转折、重大决策、关键承诺）
- 双方达成了重要共识或约定
- 用户提出了重大需求或解决了关键难题
- 包含值得长久记忆的重要信息

重要时输出：
{"importance": 0.8, "summary": "...", "keywords": [...], "emotion": "positive"}

不重要时输出：
{"importance": 0.2}
```

评分 `< importance_threshold` 时条目被丢弃，不写入 store。

## 容量管理与溢出迁移

`MilestoneStore` 按 `max_milestones` 限制容量。超出时按重要性升序排列，驱逐最低分条目并返回给调用方。`MemoryProcessor.commit()` 会将被驱逐的条目以 `[迁移自里程碑]` 前缀写入 L3 长期向量库，确保不丢失。

```
milestone.try_add(q, a, steps)
    │
    ├─ importance < threshold → 丢弃，返回 (False, [])
    └─ importance >= threshold
            │
            ▼
        store.add(entry)
            │
            ├─ len <= max_milestones → 返回 (True, [])
            └─ len > max_milestones  → 驱逐最低分条目，返回 (True, evicted)
                                            │
                                            ▼ （MemoryProcessor 处理）
                                        long.add("[迁移自里程碑] ...")
```

## 检索：`MilestoneRetriever`

无需 FAISS，基于轻量关键词匹配：

1. **精确子串匹配**（主信号）：条目关键词作为整体字符串出现在 query 中
2. **分词重叠**（次级信号）：优先使用 jieba，未安装时自动降级为字符 bigram

两路信号加权合并后取 `top_k_retrieve` 个高分条目。

## Prompt 注入格式

`retrieve()` 返回的文本直接注入 `MemoryResult.milestone`，格式如下：

```
## 重要里程碑
[2026-04-10 08:23 UTC][positive] 用户决定换工作，希望寻求建议
Q: 我打算辞职，去创业...
A: 这是个重大决定，建议先...

[2026-04-15 14:01 UTC] 用户确认完成了简历更新
```

`inject_detail=False` 时仅保留 `[时间戳] summary` 一行，不展开 Q&A 正文。

## 配置

| 参数 | 默认值 | 说明 |
|---|---|---|
| `enabled` | `False` | 是否启用里程碑记忆 |
| `milestone_dir` | `".react/milestones"` | 持久化目录（存放 `milestones.json`） |
| `max_milestones` | `50` | 内存中最大条目数，超出驱逐最低分 |
| `importance_threshold` | `0.6` | LLM 评分达到此值才写入 |
| `max_keywords` | `5` | 每条目最多关键词数 |
| `max_summary_chars` | `200` | summary 字符上限 |
| `max_detail_chars` | `1000` | detail 字符上限 |
| `top_k_retrieve` | `2` | 每次检索返回的最大条目数 |
| `inject_detail` | `True` | Prompt 中是否展开完整 Q&A detail |
| `prompt_header` | `"## 重要里程碑"` | 注入块的标头文本 |
