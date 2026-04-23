# react/memory/medium_term

基于滚动蒸馏（Rolling Distillate）的中期记忆。当短期记忆驱逐旧 Step 时，将其收集并在积累到阈值后调用 LLM 提炼出关键知识，不断迭代覆盖，Token 占用固定在 200–500。

## 核心类：`MediumTermMemory`

```python
from config.react.memory.medium_term_config import MediumTermMemoryConfig
from react.memory.medium_term import MediumTermMemory

cfg = MediumTermMemoryConfig(distill_trigger_steps=4, max_distillate_tokens=400)
mid_mem = MediumTermMemory(cfg, llm=llm)

# 在 ReActLoop 每步后调用
evicted = short_mem.add(step)
mid_mem.absorb(evicted)

# 读取蒸馏文本注入 Prompt
if mid_mem.has_distillate:
    print(mid_mem.distillate)

# 会话结束时强制蒸馏剩余 pending steps（由 commit() 调用）
mid_mem.flush()
```

## 配置

| 参数 | 默认值 | 说明 |
|---|---|---|
| `enabled` | `True` | 是否启用中期记忆 |
| `distill_trigger_steps` | `4` | 积累多少被驱逐 Step 后触发蒸馏 |
| `max_distillate_tokens` | `400` | 告知 LLM 的蒸馏文本长度上限（词数） |

## 滚动蒸馏流程

```
短期记忆驱逐 Step
    │
    ▼
MediumTermMemory.absorb(steps)
    │
    ├─ len(pending) < distill_trigger_steps → 暂存，等待
    └─ len(pending) >= distill_trigger_steps
            │
            ▼
        _distill()
            ├─ 构建 Prompt（旧蒸馏文本 + 新 Steps）
            ├─ 调用 LLM 生成新蒸馏文本
            ├─ 覆盖 self._distillate
            └─ 清空 pending
```

## 蒸馏 Prompt 结构

```
You are a knowledge distiller for a ReAct reasoning agent.
The following steps were evicted from short-term memory. Extract only what is
genuinely useful for future reasoning, within {max_tokens} words.

Previous Distillate:
{prev_distillate}

Evicted Steps to Distill:
Thought: ...
Action: ...
...

Produce an updated distillate that captures:
1. Key facts discovered (tool results and observations that matter)
2. Successful reasoning paths (what worked and why)
3. Dead ends or failed attempts (to avoid repetition)

Output only the distillate, no preamble.
```

蒸馏目标是提炼有用事实与推理路径，而非简单压缩对话流水——这与传统"滚动摘要"的区别所在。
