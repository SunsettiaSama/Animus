# agent/react/context

会话内上下文：**当前轮的推理轨迹（Step 列表）** + **中期摘要窗口（JSONL）**。实现位于 `src/agent/react/context/`，由 **`MemoryProcessor`** 汇总；**不再包含**旧的 `agent/react/memory/` 四层目录。

---

## 目录结构

```
src/agent/react/context/
├── processor.py           # MemoryProcessor — recall / commit / clear
├── memory.py              # Step 数据结构
└── medium_term/
    └── memory.py          # RecentHistoryMemory — 蒸馏写入 + 溢出归并
```

---

## `MemoryProcessor`

- **`recall()`** → `MemoryResult(short_term=..., medium_term=...)`  
  - `short_term`：本会话已累积的 `Step`（等价原「工作记忆」）。  
  - `medium_term`：`RecentHistoryMemory.render()` 的文本（跨会话 JSONL）。  
  - **不在此处读取** Soul/STM/LTM，也不自动注入 legacy L3 / 里程碑文本。
- **`commit(question, answer)`**：追加一轮 Q&A 到中期窗口（`post_process()` 调用）。
- **`clear()`**：清空当前会话轨迹。

长期侧：**`memory_recall` 工具**在 TaoLoop 中按配置挂载（Soul `MemoryService` 与/或 legacy `LongTermMemory` / `MilestoneMemory`，二者来源均为 **`agent/soul/memory`** 门面）；轮末 **`MemoryService.ingest_turn`** 在 `cfg.db` 启用时异步写入 Soul。

详见 [agent/react/README.md](../README.md)、[agent/soul/memory/README.md](../../soul/memory/README.md)。
