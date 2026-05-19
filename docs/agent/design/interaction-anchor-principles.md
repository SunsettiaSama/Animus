# 交互锚点与期待状态机 — 设计备忘

> **状态**：已讨论、待实现（记录于 2026-05-19 前后对话）  
> **范围**：顶层原则 + Anchor 层方向；不含具体 PR 拆分。

---

## 1. 顶层原则：现实锚点 = 对话

**有且仅有的现实锚点**是与真实世界主体（用户 / 频道 / Bot 会话等）之间的 **对话（dialogue）**。

- **用户发起**：用户说 → Agent 回  
- **Agent 发起**：Agent 说 → 用户可回  

二者在定义上 **同等**，不是两种锚点，也不是「只有入站才算现实」。

**推论**

- 凡不能表述为「对话（或对话中的一回合 / 一段可闭合的会话）」的，不属于现实锚点。  
- Virtual 层（地标、意外、wander 反刍、内心叙事等）是主观/虚构生命体验，**不是**现实锚点。  
- 调度摘要、会话 `open/close` 等若留在 Anchor Chronicle，仅是 **围绕对话的客观旁证**，不单独构成第二类现实。

**与当前代码的对应**

- `anchor/`：现实锚点层（内化、Chronicle、出站意图）。  
- `virtual/`：虚拟生命层。  
- 出站 `ProactiveOutboundPort` 的设计意图是 **Agent 发起对话**，但运行时投递管线尚未接通（见 §6）。

---

## 2. 离散实现 vs 全局状态机

计算机底层是离散的；「连续的生命感」在实现上 = **较密的离散更新**（心跳、漂移、回合、事件），而非真连续仿真。

**设计取向**

| 机制 | 适用 |
|------|------|
| **离散事件** | Soul 整体：tick、队列、Heartbeat checklist、体验写入 |
| **局部状态机** | **仅**锚点层的「会话」— 状态少、边界清晰 |
| **不宜** | 把整个 Soul（virtual + memory + persona）压成一张全局 FSM |

ReAct 的 `think → act → observe` 可视为 **Agent 应答子过程** 上的小状态机，不是生命主时钟。

---

## 3. ReAct 的定位（agent/react）

**结论**：ReAct 范式在 Soul/Life **主时钟** 层面不合适；在 **对话中部分 Agent 回合** 层面仍然合适。

| 层 | ReAct 是否合适 |
|----|----------------|
| 现实锚点 — 用户提问后需工具/多步的 **Agent 应答轮** | ✅ 作为执行策略 |
| 现实锚点 — **Agent 先开口**（问候、提醒、单向送达） | ⚠️ 通常不需完整 ReAct；先对话化，再决定是否深推理 |
| Virtual（地标、意外、fabricate） | ❌ 叙事引擎 + 时间触发 |
| Persona / Memory 漂移、反刍 | ❌ 异步 worker + tick |

**原则句**

> **对话是锚点；ReAct 是对话中某一类 Agent 回合的实现策略，不是锚点本身。**

**当前拓扑问题（待实现时修）**

- `TaoLoop.stream(question)` 入口偏 **用户驱动**；  
- Scheduler `TaskRunner` → `notify_fn` / `channel_router` **旁路** Life 出站链；  
- `submit_proactive_outbound` / `list_pending` 无运行时消费方。

---

## 4. 核心原则（拟确立）：期待驱动的会话内化状态机

**在交互过程中，Agent 在锚点层内化一台状态机；其与交互层最核心的耦合点是：Agent 对用户下一话语的「期待」（expectation）。**

- **对话回合** = 已发生的事实（可记账、Chronicle、ExperienceUnit）。  
- **对回复的期待** = 会话立场（stance）：此刻这段对话在「等什么」。

内化状态机 **只服务锚点**，不描述 virtual 情绪线，也不描述 ReAct 内部子步骤。

### 4.1 期待类型（初稿枚举，实现前可再收窄）

| 值 | 含义 | 典型场景 |
|----|------|----------|
| `none` | 不等待用户；会话可闭合 | `close_interaction` 之后 |
| `optional` | 已送达，用户可回可不回 | 提醒、摘要、单向通知 |
| `required` | 明确等待用户下一句 | 提问、确认、Agent 主动开口后等接话 |
| `clarify` | 等待用户澄清 | 歧义、解析失败、需确认 |
| `deferred` | 同一会话内暂不收口，语义仍可能延续 | 多步工具中间态（需约定「对用户可见交付点」才切换期待） |

**约定（待实现时细化）**

- 期待 **per `session_id`**，不全局唯一。  
- 用户跑题 / 打断 → 允许 **违背期待** 并迁移到 `clarify` 或软重置，不可卡死。  
- `optional` 需 **idle 超时** 策略（可与现有 `close_idle_interactions` 挂钩）。  
- Agent 轮交付后，根据话语性质 **更新期待**；用户轮到达后 **兑现或修正** 期待，再决定闭合或续聊。

### 4.2 与双向对话的统一

- 用户先开口：初始多为「需回应用户」→ 产出 Agent 话后 → `required` / `optional` / `none`。  
- Agent 先开口：`submit` → 投递 → `required` 或 `optional` → 用户回复 → `ack` + 内化闭合。

---

## 5. 目标架构草图（实现参考）

```
┌─────────────────────────────────────────────────────────┐
│  现实锚点：Dialogue（会话 + 回合，双向）                  │
│  内化 FSM 核心状态 = expectation（对用户下一话语的期待）  │
│  Chronicle / 会话内化 / 出站意图                         │
└─────────────────────────────────────────────────────────┘
          ▲ 只记录「发生了什么对话」
          │
┌─────────┴──────────┐    ┌──────────────────────────────┐
│ 执行面（按需）        │    │ 内在生命（时间 + 事件）       │
│ ReAct / SubAgent /   │    │ virtual / persona / memory   │
│ 轻量推送（无 ReAct）   │    │ Heartbeat checklist          │
└──────────────────────┘    └──────────────────────────────┘
```

Soul 主时钟：**时间驱动的离散事件**（已有 `LifeService`、`WorkersRegistry`、Heartbeat），不是中心 ReAct 循环。

---

## 6. 实现 backlog（明天 / 后天）

按优先级建议顺序：

1. **单 session 状态转移图**  
   - 节点：期待 ×（是否已开口 / 是否已送达）  
   - 边：`record_turn`、`submit_proactive_outbound`、`deliver`、`ack`、`close_interaction`

2. **出站管线对话化**  
   - `list_pending` → ChannelRouter / Session / Bot 投递  
   - 投递时写入 Anchor（`interaction_open` 等）  
   - 用户回复携带 `proactive_intent_id` → `acknowledge`  
   - Scheduler push 经 Anchor 出站，避免旁路

3. **在 `InteractionSession`（或等价对象）上显式挂 `expectation` 字段**  
   - 日志与 Chronicle 可观测  
   - 与 `AnchorInternalizer` 闭合逻辑对齐

4. **划定 `optional` vs `required` 产品规则**  
   - 例：调度提醒 → `optional`；Agent 问候 → `required`（待产品确认）

5. **文档同步**  
   - [life/README.md](../soul/life/README.md) 目录树仍偏旧（扁平 chronicle/journal），实现后重写

6. **（可选）Soul 工具 / API**  
   - `LifeAction` 增加 proactive 相关 action（若走 HTTP dispatch）

---

## 7. 讨论中已否决或暂缓的方向

- 用 **100ms 级** 全局情绪 tick 替代现有心跳 — 暂缓；先统一事件与锚点 FSM。  
- 用 **一张全局 Soul 状态机** 涵盖 virtual + memory — 不采纳；仅锚点会话用 FSM。  
- 用户消息 **完全不进** 多步推理 — 不采纳；复杂轮仍用 ReAct（或同类执行器）。

---

## 8. 相关源码入口（当前仓库）

| 路径 | 说明 |
|------|------|
| `src/agent/soul/life/anchor/layer.py` | 现实锚点层 |
| `src/agent/soul/life/anchor/internalization/` | Turn 缓冲、会话闭合、合成 ExperienceUnit |
| `src/agent/soul/life/anchor/outbound/port.py` | 出站意图（占位 `InMemoryProactiveOutbound`） |
| `src/agent/soul/life/manager.py` | Life 统一入口 |
| `src/agent/soul/life/service.py` | life-worker |
| `src/agent/react/tao.py` | `record_turn` / `close_interaction`（无 proactive 接线） |
| `src/agent/soul/heartbeat/task_runner.py` | Scheduler push（旁路） |

---

## 9. 原则句汇总（便于 code review 对照）

1. **有且仅有的现实锚点 = 与真实主体的对话（用户发起与 Agent 发起同等）。**  
2. **Soul 主时钟 = 离散事件 + 时间驱动，不是中心 ReAct 循环。**  
3. **ReAct = 对话中部分 Agent 回合的执行策略，不是锚点。**  
4. **锚点层内化状态机以「对用户下一话语的期待」为核心状态；回合是事实，期待是立场。**
