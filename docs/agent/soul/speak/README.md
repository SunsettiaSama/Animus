# agent/soul/speak

**对话编排子系统**：在 Soul 域内完成 Prompt 组装 → LLM 推理 → 流式出站 → 体验记账的全链路。与 `TaoLoop` 并行存在——HTTP / WebUI 对话可走 `SpeakService.run_turn`；ReAct 环仍通过 Tao 工具访问 Soul 各域。

源码：`src/agent/soul/speak/`。

---

## 顶层导出

```python
from agent.soul.speak import (
    SpeakService, SpeakHandler, SpeakTurnResult,
    SpeakPromptComposer, SpeakPromptBundle,
    SpeakDriveBridge, SpeakDriveResult,
    SpeakOutboundRouter, SpeakStreamPipeline,
    SpeakSessionRegistry, parse_agent_output,
    SpeakAction,
)
```

---

## 目录结构

```
src/agent/soul/speak/
├── service.py              # SpeakService — 编排主入口
├── drive.py                  # SpeakDriveBridge — presence 冲动 → should_speak
├── ports.py                  # Speak*Port 协议
├── compose/
│   ├── composer.py           # SpeakPromptComposer
│   ├── bundle.py             # SpeakPromptBundle / SpeakTurnMode
│   ├── runner.py             # SpeakComposeRunner（后台预组装）
│   ├── frame.py              # PreparedComposeFrame
│   ├── reply_style.py
│   ├── context/              # SpeakContextDistiller（多轮压缩）
│   ├── injected/             # persona / status 注入块
│   ├── recall/               # perform_recall_handoff
│   ├── share/                # ShareDesireComposer（分享冲动 handoff）
│   └── system/               # system prompt / output_format
├── io/
│   ├── handler.py            # SpeakHandler（Soul dispatch 入口）
│   ├── actions.py            # SpeakAction 常量
│   ├── inbound/              # 用户输入、compose gateway、memory gateway
│   │   ├── ingest.py
│   │   ├── bridge.py         # SpeakDialogueBridge
│   │   ├── compose/          # InboundComposeGateway（presence 更新触发 prepare）
│   │   ├── memory/           # InboundMemoryGateway / RecallRequest
│   │   └── session/          # SpeakSessionBridge
│   └── outbound/
│       ├── router.py         # SpeakOutboundRouter（stream / presence / text）
│       ├── deliver.py
│       └── stream/           # pipeline / parse / flush / protocol
├── session/
│   ├── service.py            # SpeakSessionManager
│   ├── turn.py               # run_session_turn
│   ├── chunk.py              # SpeakTurnChunk / 主观字段解析
│   ├── lifecycle/            # registry、语义边界、idle 超时
│   └── queue/                # user / compose 队列、打断决策
├── llm/engine.py             # SpeakLLMEngine
└── tools/                    # anchor / tao_delegate
```

---

## 核心流程

### 被动对话（`RUN_TURN`）

```
SpeakHandler._run_turn
    → SpeakService.run_turn
        ├─ SpeakSessionManager.submit_user_input
        │     ├─ agent 仍在 outward → 入 user_queue + InterruptContext
        │     └─ QueueDecisionRunner（LLM 决策 maintain / drop / reorder）
        ├─ _compose_bundle
        │     ├─ 优先 session compose queue / async PreparedComposeFrame
        │     └─ 否则 SpeakPromptComposer.compose（sync fallback）
        ├─ run_session_turn
        │     ├─ LLM generate / stream_generate
        │     ├─ share handoff / recall handoff（二次 LLM）
        │     └─ parse_agent_output（think / speak / state / recall / share 标签）
        ├─ SpeakStreamPipeline
        │     parse → flush(segment|token_batch) → SpeakStreamChannel
        └─ record_turn → LifeExperienceStack.record_dialogue_turn
```

### 主动 outbound（presence 驱动）

```
presence.discharge / expectation scan
    → SoulService._emit_presence_speak(SpeakRequest)
    → SpeakOutboundRouter.emit_presence
    → SpeakService.handle_proactive / deliver_agent_message
```

### 内驱评估

`SpeakDriveBridge` 读取 `PresenceService.snapshot()`，经 `ShareDesireComposer.evaluate_drive()` 判断 `should_speak`（分享意愿或 `impulse_level` 达阈值）。供 heartbeat、expectation scan 与外部 API 查询。

---

## SpeakAction 速查

| Action | 说明 |
|---|---|
| `open_session` / `close_session` | 会话生命周期 |
| `run_turn` | 完整一轮 compose → LLM → stream → record |
| `record_dialogue` | 仅记账（无 LLM） |
| `deliver` / `generate` / `generate_stream` | 出站 / 生成变体 |
| `drive_snapshot` / `evaluate_drive` | 内驱快照与评估 |
| `working_memory` / `dialogue_state` | 对话工作记忆查询 |

---

## 与 Soul 其它域的集成

| 域 | 集成点 |
|---|---|
| **presence** | compose 注入当下态；status listener → InboundComposeGateway 预组装；drive 读 impulse / share |
| **persona** | compose 注入 ProfileBlock / SelfConceptBlock（经 SoulService 快照） |
| **memory** | recall handoff → InboundMemoryGateway |
| **life/experience** | `record_turn` → `LifeExperienceStack.record_dialogue_turn` |
| **SoulService** | lazy wiring `_ensure_speak_service()`；`speak_turn()` 门面 |

---

## 相关文档

- [presence/README.md](../presence/README.md)（冲动 / 分享 / outbound 门控）
- [life/README.md](../life/README.md)（对话体验 pipeline）
- [agent/soul/README.md](../README.md)（SoulService 总览）
