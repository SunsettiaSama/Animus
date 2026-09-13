# agent/soul/speak

Speak 负责会话入站、导演决策、Prompt 组装、主 LLM 回复、流式交付与 Life 体验记账。入口是 `SpeakService.run_turn()`。Soul 对外 L0 是 `speak_run_turn()`；`speak_turn()` 只是转到同一入口，不再走 `dispatch(RUN_TURN)`。Speak/Worker 分类在 [`agent/inbound`](../../inbound/README.md)，不在本模块。

## 当前管线

`pipelines/types.py` 的实际状态：

```text
SpeakPipelineName = legacy_qa | request_driven | rhythm
DEFAULT_SPEAK_PIPELINE = request_driven
normalize_speak_pipeline() 仅接受 request_driven、rhythm
```

| 管线 | 公共入口状态 | 正文与交付 |
|---|---|---|
| `request_driven` | 默认、可选择 | 导演决定 gate/节奏；Compose 后由主会话 LLM 生成正文，再按导演 segment 模板交给 `DeliveryExecutor` |
| `rhythm` | 可显式选择 | arc/affect/on-scene/rhythm 导演决定是否开口与语气；主会话 LLM 生成并由 stream pipeline 输出 |
| `legacy_qa` | **公共入口不可达** | runner 仍在 router 中注册，但 normalize 会对 `pipeline="legacy_qa"` 抛 `ValueError`，默认值也不再指向它 |

因此 `legacy_qa` 只是仍留在内部装配中的旧实现，不应描述成生产 fallback 或可配置管线。

## 目录

```text
src/agent/soul/speak/
├── service.py
├── pipelines/
│   ├── types.py / router.py
│   ├── request_driven/
│   ├── rhythm/
│   └── legacy_qa/             已注册但公共选择不可达
├── io/
│   ├── inbound/               compose/memory/drive/presence
│   └── outbound/              stream/life/router
├── session/                   lifecycle、queue、typing、social
├── llm/                       主回复 LLM 与 director LLM
└── tools/
```

## 默认 `request_driven`

```text
run_turn
  → normalize(request_driven)
  → session queue / typing handoff
  → DirectorCoordinator + OrchestratorThread
       生成 speak_gate 与节奏 DeliveryPlan
  → _compose_bundle
  → _generate_request_driven_reply
       主会话 LLM，最多 8 轮处理 append/share/recall 状态
  → _pace_delivery_plan_with_speak
       用正文替换导演 segment 文本，仅保留 wait/continuity 节奏
  → stream=True: DeliveryExecutor
     stream=False: 返回组装后的 answer
  → record_dialogue → Life
```

当前回复者链路已经闭合到主会话 LLM；导演不再是最终正文的权威来源。仍需注意：

- gate 不是 `speak/brew`、计划缺失或计划为空时会返回空 answer。
- 主 LLM 没有可解析 speak 文本时也返回空 answer。
- `stream=True` 只有绑定了 stream port 才能真正到达外部连接；事件在进程内产生不等于客户端已收到。

## `rhythm`

`rhythm` 维护独立 `RhythmStateStore`：

1. 初始化/更新 arc。
2. 按频率刷新 affect 与 on-scene。
3. 根据 typing、working memory、share queue 和 context distill 生成 rhythm plan。
4. gate 为 hold/listen 时合法地不回复。
5. gate 允许开口时，将 rhythm/分享 handoff 注入 bundle，由主 LLM 生成；成功后才消费对应 share item 并记账。

`review_rhythm_session()` 只生成节奏回顾，不是一次用户出站。

## 真实 outbound

### 回合回复

- `request_driven`：`DeliveryExecutor.execute()` → `SpeakStreamChannel` → 已绑定 `SpeakStreamPort`。
- `rhythm`：`SpeakStreamPipeline.stream_generate()`/`emit_parsed_output()` → 同一 stream channel。
- 非流式调用返回 `SpeakTurnResult.answer`，调用方负责 HTTP/WS 响应。

### Presence 主动发话

```text
Presence discharge / expectation scan
  → SoulService._handle_presence_speak_trigger
  ├── 活跃会话：share intents 注入当前 session，跳过新主动会话
  └── 无活跃会话：
      PresenceSpeakIO
      → SpeakPresenceInboundBridge.initiate_proactive
      → open Life/Speak outbound + deliver_agent_message（内部记账）
      → agent-initiated handlers（例如 WebUI 推送）
```

这里的 `message` 是 Presence package/reason，不会自动再经过主 LLM 改写。若没有注册 agent-initiated handler，内部状态与体验仍会记录，但没有外部 UI 投递；不得称为已发送到用户。

Silence break、enter greeting 和 brew queue 也要求 live stream session；无 stream port/连接时会跳过或只保留内部队列。

## 主要 API

- `run_turn(..., pipeline=None|"request_driven"|"rhythm")`
- `set_stream_port()` / Soul `bind_speak_stream_port()`
- `on_typing_pulse()`、`director_snapshot()`、`review_rhythm_session()`
- `enqueue_proactive_brew()`、`evaluate_drive()`
- `record_dialogue()`、`deliver_agent_message()`
- `session_trace_cache()`、`set_session_prompt_trace()`

## 跨域接线

- Presence：snapshot、share queue、主动发话入口。
- Persona：compose portrait/distill。
- Memory：keyword、point emergence、portrait、recall handoff。
- Life：session lifecycle 与 dialogue experience。
- Storyview：通过 `StoryPort` 提供 scene block；每个已记录 user cue 也会 `push_cue()`。

这些端口由 `SoulService` 组合；单独构造 `SpeakService` 时未绑定的 Memory、Storyview 或 stream 能力不可视为可用。
