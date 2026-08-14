# agent/soul/persona

Persona 是静态画像、体验聚类 buffer、慢变 self concept 与面向对话的 persona distill。快变情绪和当下状态属于 Presence。

## 当前结构

```text
src/agent/soul/persona/
├── manager.py / service.py
├── profile/                 原始/构建后画像与 Prompt block
├── buffer/                  cluster signal、持久化、月度 drift
├── self_concept/            belief、block、store
├── distill/                 对话切片 schema/writer/store/ensure/render
├── builder.py
├── portrait.py
└── render_voice.py
```

`distill/` 是当前正式组成，不应只描述为 profile + buffer + self_concept 三层。

## `PersonaManager` / `PersonaService`

`PersonaManager` 持有状态与存储，`PersonaService` 是 Soul handler 使用的域服务包装。

主要 API：

- `snapshot()`：profile、buffer 摘要、self_concept、attention keywords，以及可用时的 `persona_distill`。
- `buffer_snapshot(include_signals=...)`
- `record_cluster_signals()`：Memory persona clusters → buffer。
- `run_monthly_drift(force=False, month="")`
- `portrait_revision()` / `portrait_for_narrative()`
- `all_blocks()` / `bias_query()`
- `reload_profile()` / `rebuild_profile()`
- `reset_self_concept()`
- `ensure_distill()` / `get_distill()`
- `sync_presence_expectation()`：根据 persona 选择 Presence 分享档位。

`snapshot()` 会同步 ensure distill；没有 LLM 或输入不足时 distill 可能为空，调用方必须处理缺失，不能假设一定有 dialogue slice。

## 写入与 worker

`SoulService._wire_workers()`：

- 把 `SoulWorkers.persona` 注入 Persona。
- 注入 Memory drift port 和 Memory embedder。
- Memory wander 的 cluster candidates 经 persona worker 写入 buffer。
- monthly drift 是 Heartbeat 重任务，使用 buffer + Memory drift units 更新 self concept。

未注入 worker 时 manager 会同步执行写入；未注入 Memory port/embedder 时月度 drift 的数据/聚类能力受限，不应描述为完整后台演化。

## Prompt 与 distill

`PersonaManager.all_blocks()` 仍只直接返回：

1. `ProfileBlock`
2. 非空时的 `SelfConceptBlock`

Speak 的 request-driven compose 另外读取 persona snapshot/distill。`PersonaDistillPack` 提供按用途的切片，dialogue slice 由 `ensure_distill()` 生成或从 store 读取。

## Soul API

Persona 的 Soul dispatch actions 定义在 `agent/soul/handlers/api/actions.py`，包括 snapshot、buffer、monthly drift、reload/rebuild profile、portrait、reset 与 distill 相关操作。外部优先使用 `SoulService.get_persona_snapshot()` / `query_persona()`：

- `get_persona_snapshot()` 只返回 Persona。
- `query_persona()` 额外叠加 Presence state、affect 与 self narrative。

## Tao adapters

当前路径是 `src/agent/adapters/soul_tao/`：

- `persona.py`：`TaoPersonaHandler`，仅处理 Tao run；monthly drift 不经 Tao。
- `persona_prompt.py`：从 Soul query 组装 Profile、SelfConcept、Presence blocks。
- `tools/persona.py`：`soul_persona` ReAct action。
- `blocks/presence_block.py`：Presence Prompt block。

不存在 `agent/soul/handlers/tao/blocks/` 或 `speak/injected/persona/` 这类当前路径。

## 持久化

Persona 使用 `StorageConfig.resolve_persona_dir()` 后的目录，主要包括：

- `profile.json` 与构建后 profile 文件
- `self_concept.json`
- buffer state/meta
- persona distill store

这些文件不随 Soul 的 Memory/Accounts/Storyview storage backend 切换。
