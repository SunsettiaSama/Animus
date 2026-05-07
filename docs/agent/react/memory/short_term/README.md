# agent/react/memory/short_term

L1 短期记忆：Token 级滑动窗口，同时受步骤数和 Token 数双重约束；窗口溢出时可选用 LLM 将被驱逐的步骤蒸馏为摘要，避免推理上下文断裂。

## 核心类：`ShortTermMemory`

```python
from config.agent.memory.short_term_config import ShortTermMemoryConfig
from agent.react.memory.short_term import ShortTermMemory

cfg = ShortTermMemoryConfig(max_turns=10, max_tokens=2048, distill_enabled=True)
memory = ShortTermMemory(cfg, llm=llm)

# 每个推理步骤后调用，返回被驱逐的步骤（已由内部蒸馏逻辑处理）
evicted = memory.add(step)

# session 结束时强制蒸馏剩余 pending 步骤（由 processor.commit() 调用）
memory.flush()

# 当前蒸馏摘要文本（注入 Prompt 的 L1 Distillate 块）
text = memory.distillate
```

## 配置

| 参数 | 默认值 | 说明 |
|---|---|---|
| `enabled` | `True` | 是否启用短期记忆 |
| `max_turns` | `10` | 滑动窗口保留的最大步骤数 |
| `max_tokens` | `2048` | Token 上限（与 max_turns 取最严格约束） |
| `distill_enabled` | `True` | 是否在溢出时启用 LLM 蒸馏 |
| `distill_trigger_steps` | `4` | 积累 N 个被驱逐步骤后触发一次蒸馏 |
| `max_distillate_tokens` | `400` | 蒸馏结果的 token 上限（作为 Prompt 指令告知 LLM）|

## 滑动逻辑

每次 `add()` 后执行 `_slide()`：从队列头部弹出最旧 Step，直到同时满足：

```
len(steps) ≤ max_turns  AND  token_count ≤ max_tokens
```

## 蒸馏逻辑

```
add(step)
    │
    ▼
_slide() → evicted: list[Step]
    │
    ├─ evicted 为空 / llm 不可用     → 结束
    └─ evicted 非空 + llm 可用
            │
            ▼
        pending.extend(evicted)
            │
            ├─ len(pending) < distill_trigger_steps  → 暂存，等待
            └─ len(pending) >= distill_trigger_steps
                    │
                    ▼
                _distill()
                    ├─ 构建 Prompt（旧摘要 + 新驱逐步骤）
                    ├─ 调用 LLM，生成新摘要
                    ├─ 覆盖 self._distillate（追加式）
                    └─ 清空 pending
```

`flush()` 在 session 结束时强制触发，处理未达阈值的剩余 pending 步骤。

## Token 计数器

默认使用空格分词估算，可注入真实 tokenizer：

```python
from transformers import AutoTokenizer

tok = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B-Instruct")
memory = ShortTermMemory(cfg, llm=llm, tokenizer=lambda text: len(tok.encode(text)))
```
