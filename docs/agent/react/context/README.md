# agent/react/context

该模块只管理 ReAct 自身的两类上下文：

- short-term：当前问题内已经产生的 `Step` 列表；
- medium-term：跨轮次的 `RecentHistoryMemory`，持久化到 `medium_term.jsonl`。

它不读取 Soul 图记忆，也不自动把长期记忆或里程碑拼进 Prompt。

## 真实数据流

```text
TaoLoop.stream(question)
  -> 创建 MemoryProcessor，共享 TaoLoop._medium_term
  -> 第 0 步 processor.recall()
       short_term = processor.trace 的副本
       medium_term = RecentHistoryMemory.render()
  -> 后续步骤复用第 0 步 medium_term，只更新 short_term
  -> 每次工具执行 processor.add(Step)
  -> finish 后保存 _PendingFinish
  -> 调用方执行 post_process()
       processor.commit(question, answer)
       -> RecentHistoryMemory.append()
       -> medium_term.jsonl
```

`MemoryResult` 当前只有 `short_term` 和 `medium_term` 两个字段。旧说明中的
`long_term`、`milestone`、`short_term_distillate` 不属于当前返回值。

## RecentHistoryMemory

启用 `distill_on_write` 时，每轮 Q/A 写入前调用 LLM 生成单条摘要；无 LLM 或结果为空时
写原始 Q/A。超过窗口后可将最旧的一批摘要归并为 summary-of-summaries。`render()` 按
日期输出，并受 `max_chars` 限制。列表访问由 `RLock` 保护，以协调 post-process 写入和
下一轮读取。

PromptManager 同时保留完整 Q/A history。因此 ReAct prompt 中可能同时出现：

1. system 内的 medium-term 摘要；
2. messages placeholder 内的完整已完成轮次；
3. human 内的当前问题和本轮 Step。

## 长期记忆边界

- Soul/Speak 使用自己的 memory compose、召回 handoff、working-memory distiller；
- agent Tao 在 Soul 可用时通过 `register_soul_tools()` 获得 `soul_memory_search`、
  `soul_life_chronicle` 等主动工具；
- Worker 还有 `AgentStateService.memory_distill` 生成的 `memory_portrait`，这是
  Worker system prompt 的额外输入，不是 `MemoryResult` 字段；
- 长期经验写入由 Soul/Life I/O 链负责，而非 `MemoryProcessor.commit()`。
