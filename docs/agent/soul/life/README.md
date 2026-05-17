# agent/soul/life

**生活状态子系统**：活动叙事日志（`LifeLog`）、可生成的 **`LifeProfile`**、以及 **`DailySynthesizer`** 产出的日度综合。由 **`LifeManager`** 统一编排；典型调用方为 **`HeartbeatModule`**（定时活动叙事、日终回顾）与 **`TaoLoop`**（`LifeProfileBlock` 注入 Prompt）。

源码：`src/agent/soul/life/`。

---

## 目录结构

```
src/agent/soul/life/
├── manager.py      # LifeManager — load_profile / write_activity / run_daily_review
├── log.py          # LifeLog（JSONL）、LifeLogEntry
├── profile.py      # LifeProfile、LifeProfileGenerator、LifeProfileStore
├── synthesis.py    # DailySynthesizer、DailySynthesisResult（含 scheduler_actions）
└── block.py        # LifeProfileBlock → Prompt
```

---

## 生命周期要点

- **会话开始**：`LifeManager.load_profile()` 从磁盘加载画像（可按 stale 策略刷新）。
- **心跳**：`should_write_activity()` 控制间隔；`generate_and_write_activity()` 根据调度任务文本生成第一人称短叙事写入日志。
- **日终**：`run_daily_review(static_profile, emotional_state, …)` 调用日度综合器；可对 **`scheduler_engine`** 下发 `scheduler_actions`（一次性 / cron）；随后可选刷新 **`LifeProfile`**。

---

## 与 Soul 记忆

日终或回顾可将多条已持久化的 **`MemoryUnit`** 交给 **`MemoryService.ingest_narrative`**（叙事记忆写入 LTM）；具体编排可在心跳或 LifeManager 扩展路径中接线。

---

## 相关文档

- [agent/soul/heartbeat](../heartbeat/README.md)
- [agent/soul/memory](../memory/README.md)
- [storage](../../../storage/README.md)（`.react/life/` 布局见 Storage 文档）
