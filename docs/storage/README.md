# storage — 运行时本地文件布局

本文档描述 Agent 在运行时产生的所有本地文件，包括目录结构、各文件用途、控制路径的配置字段及默认值。

---

## 总体原则

> **一个 Agent 实例，一个缓存根目录。**

所有运行时产出的文件统一放在 `.react/` 目录下，按模块分子目录。`config/` 目录是静态配置层，单独存放。

路径根目录由 `src/config/storage.py` 中的 `StorageConfig` 管理，并通过 `TaoConfig._propagate_dirs()` 自动传播到各子模块。

---

## 目录结构

```
.react/                          # Agent 唯一缓存根目录
├── history/                     # 对话历史（WebUI 写入）
│   └── {uuid}.json
├── memory/                      # 记忆层持久化
│   ├── medium_term.jsonl        # L2 中期跨 session Q&A 历史
│   ├── memories.json            # L3 长期记忆条目（插入顺序序列化）
│   └── qdrant/                  # L3 长期记忆 Qdrant 本地集合目录
│       └── collection/
│           └── long_term_memory/
│               └── storage.sqlite
├── milestones/                  # 里程碑记忆
│   └── milestones.json
├── persona/                     # 人格数据
│   ├── profile.json
│   ├── skills.json
│   ├── reflection.txt
│   ├── preference.json
│   └── emotional_state.json     # 情绪状态（EmotionalStateStore）
├── traces/                      # 推理链存档
│   └── {YYYYMMDD_HHMMSS}_{slug}.json
├── scheduler/                   # 调度任务持久化
│   ├── tasks.json               # 所有调度任务状态
│   ├── heartbeat_log.jsonl      # 心跳记录日志
│   └── results/                 # 各任务执行结果 JSON
├── timeline/                    # 会话级时间线事件
│   └── {YYYY-MM-DD}.jsonl
├── life/                        # 生活状态与日志
│   ├── life_log.jsonl           # 活动叙事日志
│   └── life_profile.json        # LLM 生成的当前生活状态画像
├── workspace/                   # 沙箱工作区文件（SandboxManager 读写）
└── logs/                        # 运行时观测日志
    └── obs_{YYYY-MM-DD}.jsonl
```

---

## 各模块详细说明

### 1. 对话历史 `.react/history/`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/webui/app.py` |
| 触发时机 | 每轮对话结束，前端调用 `POST /api/history` |
| 文件命名 | `{uuid}.json` |
| 路径 | `StorageConfig.history_dir`（默认 `.react/history`）|

相关 API：`GET/POST/DELETE /api/history[/{id}]`

---

### 2. L2 中期记忆 `.react/memory/medium_term.jsonl`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/agent/react/context/medium_term/memory.py`（`RecentHistoryMemory`）|
| 触发时机 | `processor.commit()` → `RecentHistoryMemory.append()` |
| 内容 | JSONL，每行一条 Q&A 对；整合后出现 `summary` 类型条目 |
| 路径配置字段 | `MediumTermMemoryConfig.memory_dir` |
| 默认值 | `".react/memory"` |

---

### 3. L3 长期记忆 `.react/memory/`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/agent/soul/memory/long_term/store.py`（`LongTermMemory`）|
| 触发时机 | **`post_process`** 中的 **`_maybe_consolidate()`**（`consolidation_k > 0` 时）；非每轮 `commit` 默认写入 |
| 文件列表 | `memories.json`、`qdrant/` |
| 路径配置字段 | `LongTermMemoryConfig.memory_dir`、`qdrant_path` |

召回：**`memory_recall` 工具**，不在 Prompt 构建阶段被动拼接。

---

### 4. 里程碑记忆 `.react/milestones/`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/agent/soul/memory/milestone/store.py` |
| 触发时机 | 由调用方显式 **`MilestoneMemory.try_add`**（当前 TaoLoop **`post_process` 默认不再调用**）；检索经 **`memory_recall`** |
| 路径配置字段 | `MilestoneConfig.milestone_dir` |
| 默认值 | `".react/milestones"` |
| 开关 | `MilestoneConfig.enabled` |

### 5. 人格数据 `.react/persona/`

| 文件 | 写入类 | 触发时机 |
|---|---|---|
| `profile.json` | `ProfileStore.save_profile()` | PersonaManager 初始化 + `persona.evolve()` |
| `skills.json` | `ProfileStore.save_skills()` | `skills_enabled=True` 时演化触发 |
| `reflection.txt` | `ProfileStore.save_reflection()` | `reflection_enabled=True` 且达到 `reflect_interval` |
| `preference.json` | `PreferenceStore.save()` | 每 `preference_update_every_n` 轮 |
| `emotional_state.json` | `EmotionalStateStore.save()` | 每轮 `persona.evolve()` 更新情绪状态 |

路径配置字段：`PersonaConfig.persona_dir`，默认 `".react/persona"`。

---

### 6. 推理链存档 `.react/traces/`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/agent/react/trace/store.py` |
| 触发时机 | `TaoLoop.post_process()` → `TraceStore.write()` |
| 文件命名 | `{YYYYMMDD_HHMMSS}_{query_slug}.json` |
| 路径配置字段 | `TraceConfig.trace_dir` |
| 默认值 | `".react/traces"` |
| 开关 | `TraceConfig.enabled`（默认 `True`）|

**单个 trace 文件结构：**

```json
{
  "id": "uuid",
  "timestamp": "2026-01-01T00:00:00+00:00",
  "question": "...",
  "answer": "...",
  "steps": [
    {
      "index": 0,
      "thought": "...",
      "action": "web_search",
      "action_input": { "query": "..." },
      "observation": "..."
    }
  ]
}
```

---

### 7. 调度任务 `.react/scheduler/`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/runtime/scheduler/store.py`、`src/runtime/scheduler/engine.py`；任务执行见 `src/agent/soul/heartbeat/task_runner.py` |
| `tasks.json` | 所有调度任务的状态（TaskStore 持久化）|
| `heartbeat_log.jsonl` | 心跳检查记录（HeartbeatTickLog）|
| `results/` | 各任务执行结果，文件名为 `{task_id}.json` |
| 路径配置字段 | `SchedulerConfig.scheduler_dir` |

---

### 8. 时间线 `.react/timeline/`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/runtime/scheduler/timeline.py`（或经 TaoLoop 挂载的 TimelineService）|
| 触发时机 | Scheduler 任务完成后追加时间线事件 |
| 文件命名 | `{YYYY-MM-DD}.jsonl`（每日一个文件）|
| 路径配置字段 | `StorageConfig.timeline_dir`（`".react/timeline"`）|

---

### 9. 生活状态 `.react/life/`

| 文件 | 写入类 | 触发时机 |
|---|---|---|
| `life_log.jsonl` | `LifeLog.append()` | 心跳每 N 小时写入活动叙事 |
| `life_profile.json` | `LifeProfileStore.save()` | `LifeProfileGenerator` LLM 刷新当前生活状态 |

路径配置字段：`StorageConfig.life_dir`（`".react/life"`）。

---

### 10. 工作区 `.react/workspace/`

沙箱工作区文件由 `SandboxManager` 管理，工具 `file_read` / `file_write` / `file_list` 的所有操作均限定在此目录内。

路径配置字段：`StorageConfig.workspace_dir`（`".react/workspace"`）。

---

### 11. 观测日志 `.react/logs/`

| 项目 | 说明 |
|---|---|
| 内容 | 运行时观测事件（LLM 调用、工具执行等）|
| 文件命名 | `obs_{YYYY-MM-DD}.jsonl` |
| 路径配置字段 | `StorageConfig.obs_dir`（`".react/logs"`）|

---

## 路径配置字段一览

| 文件/目录 | StorageConfig 属性 | 默认值 |
|---|---|---|
| `.react/history/` | `history_dir` | `".react/history"` |
| `.react/memory/` | `memory_dir` | `".react/memory"` |
| `.react/milestones/` | `milestones_dir` | `".react/milestones"` |
| `.react/persona/` | `persona_dir` | `".react/persona"` |
| `.react/traces/` | `traces_dir` | `".react/traces"` |
| `.react/scheduler/` | `scheduler_dir` | `".react/scheduler"` |
| `.react/timeline/` | `timeline_dir` | `".react/timeline"` |
| `.react/life/` | `life_dir` | `".react/life"` |
| `.react/workspace/` | `workspace_dir` | `".react/workspace"` |
| `.react/logs/` | `obs_dir` | `".react/logs"` |
| `.react/benchmark/` | `benchmark_dir` | `".react/benchmark"` |

路径均相对于进程 CWD，建议始终在仓库根目录下运行（`python src/run.py`）。

---

## 写入触发时序

```
用户发送消息
├─ [Chat 模式]
│    └─ LLM 回复完成 → 前端 saveConv() → POST /api/history
│                                         → .react/history/{uuid}.json ✎
│
└─ [ReAct 模式]
     └─ TaoLoop.stream()
          └─ 收到 FinishEvent → 前端 saveConv() → .react/history/{uuid}.json ✎
               └─ TaoLoop.post_process()（后台线程）
                    ├─ MemoryProcessor.commit()
                    │    └─ RecentHistoryMemory.append()  → .react/memory/medium_term.jsonl ✎
                    ├─ MemoryService.ingest_turn（可选线程）→ Soul MySQL / Redis ✎
                    ├─ _maybe_consolidate()（可选）→ LongTermMemory ✎
                    ├─ TraceStore.write()                 → .react/traces/ ✎
                    └─ PersonaManager.evolve()
                         ├─ ProfileStore.save_*()         → .react/persona/ ✎
                         ├─ PreferenceStore.save()        → .react/persona/preference.json ✎
                         └─ EmotionalStateStore.save()   → .react/persona/emotional_state.json ✎

Scheduler（后台轮询）
     └─ TaskRunner.run()                                  → .react/scheduler/results/ ✎
          └─ TimelineService.append()                   → .react/timeline/{date}.jsonl ✎

HeartbeatModule（后台心跳）
     ├─ LifeLog.append()                                  → .react/life/life_log.jsonl ✎
     ├─ LifeProfileStore.save()                           → .react/life/life_profile.json ✎
     └─ HeartbeatTickLog.append()                         → .react/scheduler/heartbeat_log.jsonl ✎
```

---

## 清理

```bash
# 清空对话历史（保留其他数据）
curl -X DELETE http://localhost:8300/api/history
# 或
rm .react/history/*.json

# 清空全部运行时数据
rm -rf .react/
```
