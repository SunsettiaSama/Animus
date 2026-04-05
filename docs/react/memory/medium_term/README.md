# react/memory/medium_term

基于滚动摘要（Rolling Summary）的中期记忆。当短期记忆驱逐旧 Step 时，将其收集并在积累到阈值后调用 LLM 生成一段精简摘要，不断迭代覆盖，Token 占用固定在 200–500。

## 核心类：`MediumTermMemory`

```python
from config.react.memory.medium_term_config import MediumTermMemoryConfig
from react.memory.medium_term import MediumTermMemory

cfg = MediumTermMemoryConfig(summary_trigger_steps=4, max_summary_tokens=400)
mid_mem = MediumTermMemory(cfg, llm=llm)

# 在 ReActLoop 每步后调用
evicted = short_mem.add(step)
mid_mem.absorb(evicted)

# 读取摘要注入 Prompt
if mid_mem.has_summary:
    print(mid_mem.summary)
```

## 配置

| 参数 | 默认值 | 说明 |
|---|---|---|
| `summary_trigger_steps` | `4` | 积累多少被驱逐 Step 后触发摘要 |
| `max_summary_tokens` | `400` | 告知 LLM 的摘要长度上限 |

## 滚动摘要流程

```
短期记忆驱逐 Step
    │
    ▼
MediumTermMemory.absorb(steps)
    │
    ├─ len(pending) < trigger_steps → 暂存，等待
    └─ len(pending) >= trigger_steps
            │
            ▼
        _roll_summary()
            ├─ 构建 Prompt（旧摘要 + 新 Steps）
            ├─ 调用 LLM 生成新摘要
            ├─ 覆盖 self._summary
            └─ 清空 pending
```

## 摘要 Prompt 结构

```
You are a memory summarizer...

Previous Summary: {prev_summary}

New Steps to Absorb:
Thought: ...
Action: ...
...

Write only the updated summary.
```
