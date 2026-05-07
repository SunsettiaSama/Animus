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
│   ├── memories.json            # L3 长期记忆条目
│   └── memory_index.faiss       # L3 长期记忆 FAISS 索引
├── milestones/                  # 里程碑记忆
│   └── milestones.json
├── persona/                     # 人格数据
│   ├── profile.json
│   ├── skills.json
│   ├── reflection.txt
│   └── preference.json
├── traces/                      # 推理链存档
│   └── {YYYYMMDD_HHMMSS}_{slug}.json
└── scheduler/                   # 调度任务持久化
    ├── tasks.json               # 所有调度任务状态
    └── results/                 # 各任务执行结果 JSON
```

---

## 各模块详细说明

### 1. 对话历史 `.react/history/`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/webui/app.py` |
| 触发时机 | 每轮对话结束，前端调用 `POST /api/history` |
| 文件命名 | `{uuid}.json` |
| 路径 | WebUI 硬编码于 `_HISTORY_DIR`，不经由 StorageConfig |

相关 API：`GET/POST/DELETE /api/history[/{id}]`

---

### 2. L2 中期记忆 `.react/memory/medium_term.jsonl`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/agent/react/memory/medium_term/memory.py` |
| 触发时机 | `processor.commit()` → `RecentHistoryMemory.append()` |
| 内容 | JSONL，每行一条 Q&A 对；整合后出现 `summary` 类型条目 |
| 路径配置字段 | `MediumTermMemoryConfig.memory_dir` |
| 默认值 | `".react/memory"` |

---

### 3. L3 长期记忆 `.react/memory/`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/agent/react/memory/long_term/store.py` |
| 触发时机 | `processor.commit()` → `LongTermMemory.save()` |
| 文件列表 | `memories.json`（条目元数据）、`memory_index.faiss`（FAISS 索引）|
| 路径配置字段 | `LongTermMemoryConfig.memory_dir` |
| 默认值 | `".react/memory"` |

**`memories.json` 结构：**

```json
[
  {
    "id": "uuid",
    "created_at": "2026-01-01T00:00:00+00:00",
    "text": "Q: ...\nA: ...",
    "meta": { "question": "..." }
  }
]
```

召回结果均携带时间戳前缀 `[YYYY-MM-DD HH:MM UTC]`。

---

### 4. 里程碑记忆 `.react/milestones/`

| 项目 | 说明 |
|---|---|
| 写入模块 | `src/agent/react/memory/milestone/store.py` |
| 触发时机 | `processor.commit()` → `MilestoneMemory.try_add()`（LLM 评分 ≥ 阈值时）|
| 路径配置字段 | `MilestoneConfig.milestone_dir` |
| 默认值 | `".react/milestones"` |
| 开关 | `MilestoneConfig.enabled`（默认 `False`）|

---

### 5. 人格数据 `.react/persona/`

| 文件 | 写入类 | 触发时机 |
|---|---|---|
| `profile.json` | `ProfileStore.save_profile()` | PersonaManager 初始化 + `persona.evolve()` |
| `skills.json` | `ProfileStore.save_skills()` | `skills_enabled=True` 时演化触发 |
| `reflection.txt` | `ProfileStore.save_reflection()` | `reflection_enabled=True` 且达到 `reflect_interval` |
| `preference.json` | `PreferenceStore.save()` | 每 `preference_update_every_n` 轮 |

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
| 写入模块 | `src/agent/scheduler/store.py` / `src/agent/scheduler/engine.py` |
| `tasks.json` | 所有调度任务的状态（TaskStore 持久化）|
| `results/` | 各任务执行结果，文件名为 `{task_id}.json` |
| 路径配置字段 | `SchedulerConfig.scheduler_dir` |

---

## 路径配置字段一览

| 文件/目录 | 配置字段 | 默认值 |
|---|---|---|
| `.react/history/` | WebUI 硬编码 | `<repo>/.react/history` |
| `.react/memory/` | `LongTermMemoryConfig.memory_dir` / `MediumTermMemoryConfig.memory_dir` | `".react/memory"` |
| `.react/milestones/` | `MilestoneConfig.milestone_dir` | `".react/milestones"` |
| `.react/persona/` | `PersonaConfig.persona_dir` | `".react/persona"` |
| `.react/traces/` | `TraceConfig.trace_dir` | `".react/traces"` |
| `.react/scheduler/` | `SchedulerConfig.scheduler_dir` | `".react/scheduler"` |
| `config/llm_core/config.yaml` | WebUI 硬编码 | `<repo>/config/llm_core/config.yaml` |

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
                    │    ├─ RecentHistoryMemory.append()  → .react/memory/medium_term.jsonl ✎
                    │    ├─ LongTermMemory.save()         → .react/memory/ ✎
                    │    └─ MilestoneMemory.try_add()
                    │         └─ score >= threshold → .react/milestones/ ✎
                    ├─ TraceStore.write()                 → .react/traces/ ✎
                    └─ PersonaManager.evolve()
                         ├─ ProfileStore.save_*()         → .react/persona/ ✎
                         └─ PreferenceStore.save()        → .react/persona/preference.json ✎
```

---

## 清理

```bash
# 清空对话历史（保留其他数据）
curl -X DELETE http://localhost:8080/api/history
# 或
rm .react/history/*.json

# 清空全部运行时数据
rm -rf .react/
```
