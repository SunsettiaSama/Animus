# react/memory

三级记忆系统，覆盖不同时间跨度的上下文保留需求。

```
memory/
├── memory.py           # Step + Memory（无界基础记忆）
├── short_term/         # 短期记忆：Token 滑动窗口
├── medium_term/        # 中期记忆：滚动摘要
└── long_term/          # 长期记忆：BGE Embedding + RAG（进行中）
```

## 数据单元：`Step`

```python
@dataclass
class Step:
    thought: str         # LLM 的推理过程
    action: str          # 动作名称
    action_input: dict   # 动作参数
    observation: str     # 工具返回结果
```

## 三级记忆对比

| 层级 | 实现 | Token 占用 | 保留内容 |
|---|---|---|---|
| 短期 | 滑动窗口 | 受 `max_tokens` 严格限制 | 最近 N 轮完整 Step |
| 中期 | 滚动摘要 | 固定 200–500 | 历史推理主线摘要 |
| 长期 | BGE + 向量检索 | 按需检索 | 跨会话持久知识 |

## 数据流

```
Step 产生
    │
    ▼
ShortTermMemory.add(step) → 返回 evicted: list[Step]
    │
    ├─ evicted 为空 → 无操作
    └─ evicted 非空 → MediumTermMemory.absorb(evicted)
                            │
                            ├─ pending < trigger_steps → 暂存
                            └─ pending >= trigger_steps → 调用 LLM 生成摘要（覆盖旧摘要）
```

子模块详细文档：
- [short_term](./short_term/README.md)
- [medium_term](./medium_term/README.md)
- [long_term/embedding](./long_term/embedding/README.md)
