# agent/react/memory/medium_term

L2 中期记忆：跨 session 的近期 Q&A 历史，以 JSONL 文件持久化，每次 session 启动时加载最近 N 天的记录注入 Prompt。

## 核心类：`RecentHistoryMemory`

```python
from config.agent.memory.medium_term_config import MediumTermMemoryConfig
from agent.react.memory.medium_term import RecentHistoryMemory

cfg = MediumTermMemoryConfig(window_days=7, max_entries=30)
mem = RecentHistoryMemory(cfg, llm=llm)

# 轮结束后（后台线程）追加一条 Q&A，并检查是否触发自动整合
mem.append(question, answer)

# 渲染近期历史文本注入 Prompt
text = mem.render()   # 空则返回 ""

# 手动触发整合（WebUI「立即整理」按钮）
did = mem.consolidate(force=True)
```

## 配置

| 参数 | 默认值 | 说明 |
|---|---|---|
| `enabled` | `True` | 是否启用中期记忆 |
| `window_days` | `7` | 加载最近 N 天的条目 |
| `max_entries` | `30` | 窗口内最多保留 N 条（取最新） |
| `max_chars` | `3000` | 注入 Prompt 的字符上限（超出保留最新部分） |
| `consolidate_enabled` | `True` | 是否启用滚动整合 |
| `consolidate_batch` | `10` | 每次整合的旧条目数 |
| `consolidate_interval_days` | `1` | 自动整合的最短间隔（天）；`0` = 每次提交都检查 |
| `max_consolidate_tokens` | `500` | 整合摘要的 token 上限 |

## JSONL 格式

每条记录占一行：

```json
{"ts": "2026-04-22T10:30:00+00:00", "q": "问题文本", "a": "回答文本"}
```

整合后的摘要条目：

```json
{"type": "summary", "ts": "...", "period_start": "...", "period_end": "...", "text": "摘要文本"}
```

文件位置由 `TaoConfig._propagate_dirs` 自动写入 `cfg.memory_dir`，默认为 `.react/memory/medium_term.jsonl`。

## 渲染格式

`render()` 输出示例：

```
[2026-04-15 ~ 2026-04-20] (summary)
上周用户主要讨论了 Python 异步编程和 FAISS 索引优化...

[2026-04-22]
Q: 什么是量子纠缠？
A: 量子纠缠是...
```

## 滚动整合流程

```
append(question, answer)
    │
    ▼
写入 JSONL
    │
    ▼
_maybe_consolidate()
    ├─ len(entries) ≤ max_entries       → 跳过
    ├─ consolidate_enabled = False      → 跳过
    ├─ llm 不可用                       → 跳过
    └─ 满足条件 → consolidate(force=False)
            │
            ├─ 距上次整合 < interval_days → 跳过
            └─ 取最旧 consolidate_batch 条 → LLM 蒸馏
                    │
                    ▼
              summary 条目替换旧条目
                    │
                    ▼
              重写 JSONL + 更新缓存日期
```

整合由 `commit()` 后台线程异步触发，用户无感知。`force=True` 跳过日期节流，供 WebUI 手动整合使用。
