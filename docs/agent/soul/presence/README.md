# agent/soul/presence

**当下态子系统**：以多维度 FSM 描述 Agent 第一人称「在场」状态——情感、生理、认知、感知为静态维度；期待、冲动、分享意愿为动态交互层。冲动累积后可经 `SoulService` 触发主动 Speak outbound。

源码：`src/agent/soul/presence/`。

---

## 顶层导出

```python
from agent.soul.presence import (
    PresenceService, PresenceSnapshot, PresenceGateway,
    Expectation, ImpulseDischarge, ShareDesire,
    PresenceState, PresenceContext, PresenceEvent,
    compose_self_narrative, PresenceStateBlock,
)
```

---

## 目录结构

```
src/agent/soul/presence/
├── service.py                # PresenceService — 域服务主入口
├── gateway.py                # PresenceGateway — 入站 trigger / capture
├── discharge.py              # ImpulseDischarge — 冲动释放 → outbound
├── share_desire.py           # ShareDesire 权重与 patch
├── expectation.py            # Expectation 聚合类型
├── narrative.py              # compose_self_narrative
├── state_block.py            # PresenceStateBlock → PromptBlock
├── store.py                  # PresenceStateStore 持久化
├── actions.py                # PresenceAction（orchestrator 调度用）
├── state/
│   ├── presence_state.py     # PresenceState 根
│   ├── static/               # affect / somatic / cognition / perception / narrative
│   └── dynamic/              # interaction / events / expectation（queue/scanner/package/intent）
└── transition/
    ├── router.py             # PresenceTransitionRouter
    ├── init/                 # wake / sleep
    ├── static/               # lifecycle / life_sync
    ├── dynamic/              # boundary / life_meta / edges
    └── interaction.py        # PresenceInteraction（期待 + 冲动 + 分享队列）
```

---

## 状态模型

### 静态维度（`state/static/`）

均为 Agent 第一人称自叙（字符串），不再使用结构化效价/强度：

| 维度 | 字段 |
|---|---|
| 情感 `affect` | `narrative` |
| 生理 `somatic` | `narrative` |
| 认知 `cognition` | `working_memory` / `thinking` |
| 感知 `perception` | `narrative` |

### 动态交互层（`state/dynamic/` + `transition/interaction.py`）

不属于 FSM 静态维度，由 `PresenceInteraction` 承载：

- **期待**（`expectation/`）：queue、scanner、package、intent
- **冲动**：`impulse_level` / `impulse_reason`，达阈值触发 outbound
- **分享意愿**（`ShareDesire`）：与 Speak compose share handoff 联动

---

## 核心流程

### 起床 / 休眠

心跳在每日 `presence_wake_at` 调度 `transition/init/wake.py`，以 LLM 生成四维度自叙完成 FSM 初始化；清醒窗口由 `HeartbeatConfig.active_hours_start/end` 控制，窗口外自动休眠。

### Life ↔ Presence 双向绑定

`LifeExperienceStack.bind_presence()`：

- 对话体验直写 Presence
- `ExperienceOrchestrator.after_ingest` → `presence.pull_and_sync_from_life`

### 主动 outbound

```
ImpulseDischarge / expectation scan
    → SoulService._emit_presence_speak
    → SpeakOutboundRouter
```

`SpeakDriveBridge` 读取 snapshot 评估 `should_speak`。

### 心跳信号

`MemoryHeartbeatResult` → `EmotionalSignal` → `presence.receive_heartbeat_signal`（见 `heartbeat/bridge.py`）。

---

## PresenceService 职责摘要

| 能力 | 说明 |
|---|---|
| `snapshot()` | 只读当下态 + interaction |
| `ingest_event()` / gateway | 外部事件 / 对话 capture |
| `pull_and_sync_from_life()` | 从体验热窗口同步 narrative |
| `run_expectation_scan()` | 扫描期待队列，可能触发 speak |
| `discharge()` | 冲动释放 |
| status listener | 注册后通知 Speak InboundComposeGateway |

---

## 相关文档

- [speak/README.md](../speak/README.md)（outbound / compose / drive）
- [life/README.md](../life/README.md)（LifeExperienceStack.bind_presence）
- [heartbeat/README.md](../heartbeat/README.md)（wake / wander 信号）
