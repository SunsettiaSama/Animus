# agent/soul/presence

Presence 维护按 session 隔离的当下态、互动期待、冲动与分享队列。它不是 `SoulRequest` domain；外部调用应经 `SoulService` 编排方法，域内调用使用 `PresenceService`/`PresenceGateway`。

## 当前模块

```text
src/agent/soul/presence/
├── service.py / gateway.py
├── state/
│   ├── presence_state.py
│   ├── static/                     affect/somatic/cognition/perception/narrative
│   ├── dynamic/                    interaction/events/kind
│   └── dynamic/expectation/        queue/scanner/package/state/intent
├── transition/
│   ├── init/                       wake/sleep
│   ├── static/                     lifecycle/life_sync
│   └── dynamic/                    boundary/life_meta/edges
├── init_expectation/               persona → 分享期待档位
├── unit_distill/                   近期体验画像蒸馏
├── io/speak/                       主动发话协议
└── store.py                        life_dir/presence_state.json
```

## 公共导出

`agent.soul.presence` 当前导出：

- 服务与入口：`PresenceService`、`PresenceGateway`
- 状态：`PresenceSnapshot`、`PresenceState`、`PresenceContext`
- 事件/触发：`PresenceEvent`、`PresenceEventKind`、`PresenceTrigger`、`PresenceTriggerKind`
- 结果：`GatewayResult`、`PresenceIngestResult`、transition result/outcome
- 互动：`Expectation`、`ExpectationState`、`ImpulseDischarge`、`ShareDesire`
- Prompt/存储：`PresenceStateBlock`、`PresenceStateStore`

不存在单独的 `PresenceHandler` 或 Presence domain dispatch。

## `PresenceService` 主要 API

读取：

- `snapshot(session_id)`
- `compose_self_narrative(session_id)`
- `is_awake()`、`affect_narrative()`
- `share_queue_size()`

状态与边界：

- `gateway`/`interface.boundary(event, context=...)`
- `ingest()` / `dispatch()` / `trigger()`
- `patch_static()`、`set_working_memory()`
- `wake_up()`、`sleep()`、`apply_dialogue_session_boundary()`
- `sync_from_life()`、`sync_life_bundle()`、`on_unit_ingested()`

互动与出站准备：

- `scan_expectation()`：只扫描并更新 Presence，不直接发送。
- `discharge_accumulated()`：折叠 share queue，返回 `ImpulseDischarge`。
- `pop_share_intent()` / `pop_top_share_intents()` / `consume_share_at()`
- `receive_heartbeat_signal()`

真正触发 Speak 的入口在 `SoulService.run_expectation_scan()`、`ingest_presence_event()`、`initiate_presence_conversation()` 等编排方法。

## Life、Persona 与 Heartbeat

- `LifeExperienceStack.bind_presence()` 把 dialogue/life pipelines 和 ingest 后同步接到 Presence。
- 每批 ExperienceUnit 可更新 lingering mood；达到批次且绑定了 LLM 时才运行 `unit_distill`。
- Persona 启动时通过 `init_expectation/` 解析分享档位，并热更新 Speak 阈值。
- Heartbeat 控制 active-hours wake/sleep，并把 Memory emotional signal 写入 affect。

未绑定 Life stack 时 `sync_from_life()` 会抛错；未绑定 unit-distill LLM 时只跳过近期画像蒸馏，不代表该能力已运行。

## 主动发话的实际边界

```text
Presence scan/discharge
  → SoulService
  ├── 当前有活跃对话：share intent 延迟注入现有 Speak session
  └── 无活跃对话：PresenceIOHub.speak
      → SpeakPresenceInboundBridge
      → Speak/Life 内部会话与体验记录
      → 注册的 agent-initiated handler
```

`PresenceService.scan_expectation()` 本身不发送消息。只有 Soul 完成 IO 接线且外层注册了 handler/stream 时，消息才可能到达 UI。没有外部 handler 时仅有内部 ack 和记账，必须标注为未外发。

## Tao adapters

Presence 没有 `handlers/tao/`。Tao Prompt 适配在：

- `src/agent/adapters/soul_tao/blocks/presence_block.py`
- `src/agent/adapters/soul_tao/blocks/` 中的 self-narrative block
- `src/agent/adapters/soul_tao/persona_prompt.py`（从 `SoulService.query_persona()` 同时组装 Persona 与 Presence）

## 持久化

`PresenceStateStore` 把所有 session 的 state、interaction、awake、last_wake_date 写到 `<life_dir>/presence_state.json`。这是 Life 目录文件，不随 Memory/Storyview 的 MySQL/JSON backend 切换。
