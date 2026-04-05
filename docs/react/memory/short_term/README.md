# react/memory/short_term

基于 Token 级滑动窗口的短期记忆，同时受轮数和 Token 数双重约束，取二者最严格限制。

## 核心类：`ShortTermMemory`

```python
from config.react.memory.short_term_config import ShortTermMemoryConfig
from react.memory.short_term import ShortTermMemory

cfg = ShortTermMemoryConfig(max_turns=5, max_tokens=1024)
memory = ShortTermMemory(cfg)

evicted = memory.add(step)   # 返回被驱逐的 steps（传给中期记忆）
```

## 配置

| 参数 | 默认值 | 说明 |
|---|---|---|
| `max_turns` | `10` | 最大保留轮数 |
| `max_tokens` | `2048` | Token 上限 |

## 滑动逻辑

每次 `add()` 后执行 `_slide()`：从队列头部弹出最旧 Step，直到满足：

```
len(steps) ≤ max_turns  AND  token_count ≤ max_tokens
```

`add()` 返回本次被驱逐的所有 `Step`，供中期记忆 `absorb()`。

## Token 计数器注入

默认使用空格分词估算，可替换为真实 tokenizer：

```python
from transformers import AutoTokenizer

tok = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B-Instruct")
memory = ShortTermMemory(cfg, tokenizer=lambda text: len(tok.encode(text)))
```
