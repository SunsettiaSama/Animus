# storage — 运行时本地布局与写入链

`src/config/storage.py` 的 `StorageConfig` 只定义缓存根目录及其子目录。WebUI 使用 `AppPaths.cache_root` 创建 `StorageConfig(root=<项目根>/.react)`；配置 YAML 位于项目的 `config/`，不属于运行时缓存。

## 真实目录边界

以下是当前源码声明或直接写入的布局；目录按需创建，并非启动时全部出现。

```text
.react/
├── history/
│   ├── {conversation_id}.json
│   └── agent_journal_{YYYYMMDD}.json
├── memory/
│   └── medium_term.jsonl
├── persona/
│   ├── persona_config.json
│   ├── profile.json
│   ├── built_profile.json
│   ├── self_concept.json
│   ├── persona_distill.json
│   ├── experience_buffer.jsonl
│   └── buffer_meta.json
├── scheduler/
│   ├── tasks.json
│   └── results/{task_id前8位}_{YYYYMMDD_HHMMSS}.json
├── timeline/{YYYY-MM-DD}.jsonl
├── life/
│   ├── heartbeat_log.jsonl
│   ├── experience_hot.jsonl
│   ├── life_profile.json
│   ├── anchor_chronicle.jsonl
│   ├── virtual_chronicle.jsonl
│   └── landmark_agendas.json
├── worker/agent_state.json
├── soul_db/**/*.json
├── workspace/
├── traces/
├── milestones/
├── logs/
├── benchmark/
└── train/{checkpoints,adapters,merged}/
```

`StorageConfig` 的属性为 `history_dir`、`memory_dir`、`persona_dir`、`milestones_dir`、`traces_dir`、`scheduler_dir`、`workspace_dir`、`timeline_dir`、`life_dir`、`worker_dir`、`benchmark_dir`、`obs_dir`、`train_dir`、`checkpoints_dir`、`adapters_dir` 和 `merged_dir`。

## Soul 数据库与文件缓存不是同一层

当前 Soul 的记忆图、账号和 Story 数据走 `DBConfig.storage.backend`：

- `mysql`：写入 MySQL。
- `json`：通过 `JsonStorageService` 写入 `storage.json_root`，默认 `.react/soul_db`。
- `auto`：MySQL 可达时选 MySQL，否则选 JSON。

JSON collection 名称映射为 `<json_root>/<name>.json`，例如 `memory/nodes` 写到 `.react/soul_db/memory/nodes.json`。写入采用同目录 `.tmp` 文件后 `os.replace()`。这些数据不应再描述为 `.react/memory/memories.json` 或固定的本地 Qdrant 目录。

`.react/memory/medium_term.jsonl` 属于 ReAct/Worker 的近期历史链，不是 Soul 记忆图的主存储。

## 主要写入链

### WebUI 与调度

```text
history API
  └─ .react/history/{conversation_id}.json

SchedulerEngine.schedule_*
  └─ TaskStore.add/update
       └─ .react/scheduler/tasks.json

TemporalClock
  └─ TaskRunner.run
       ├─ .react/scheduler/results/{id8}_{timestamp}.json
       ├─ TimelineService.append
       │    └─ .react/timeline/{UTC date}.jsonl
       ├─ WorkJournal.append_task_result
       │    └─ .react/history/agent_journal_{UTC date}.json
       └─ notify_fn / ChannelRouter（按 delivery 配置）
```

标准 Soul 装配把 `state.cache.life_dir` 传给 `SoulService`，再作为 `HeartbeatModule.log_dir` 传入 `HeartbeatTickLog`，因此心跳记录追加到 `.react/life/heartbeat_log.jsonl`。它不与 `tasks.json` 共用 scheduler 目录；Soul heartbeat 由 `HeartbeatCoreService` 驱动，不经过 `SchedulerEngine`。

### Soul / Speak

```text
WebUI /ws/speak/run
  └─ SoulService.speak_run_turn
       ├─ Speak 会话状态（主要为进程内状态）
       ├─ Life 体验与画像
       │    └─ .react/life/*
       ├─ Persona profile / distill / buffer
       │    └─ .react/persona/*
       └─ Memory / account / story domain stores
            ├─ MySQL
            └─ 或 .react/soul_db/**/*.json
```

Speak 不直接读写 `.react/workspace`。该目录是 `SandboxManager` 的沙箱根，由文件工具和需要文件执行的 Worker/ReAct 路径使用。TTS/STT 也不把音频落到 workspace：HTTP/WS 接口传递字节；本地 STT 只使用操作系统临时文件并在转录后删除。

### Worker 状态

WebUI 在 Soul 启动后创建 `AgentStateService`，其 `AgentStateStore` 将 worker、reflection 和 memory portrait 三个 slot 原子写入 `.react/worker/agent_state.json`。

## 路径解析

`resolve_cache_path()` 把空串、`.` 和 `./` 视为未配置并回退到对应默认目录。`TaskStore`、`HeartbeatTickLog` 和 persona stores 都通过 `StorageConfig` 做路径解析；`HeartbeatTickLog` 在标准装配中收到的是非空 life 目录，因此保留该目录。相对路径仍相对于进程当前工作目录；标准入口会使用项目根目录的绝对 `.react` 路径。
