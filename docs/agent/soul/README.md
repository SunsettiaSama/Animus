# agent/soul

Soul 子系统在 ReAct 推理环之外承载 **持久记忆单元（Redis/MySQL）**、**调度心跳**、**生活叙事与画像**、以及 **人格演化实现（PersonaManager）**。与 `agent/react/` 内的 `MemoryProcessor`、工具编排并行；`TaoLoop` 直接引用本目录下的 `PersonaManager`、`LifeManager` 等。

---

## 文档索引

| 文档 | 说明 |
|---|---|
| [memory/README.md](./memory/README.md) | `MemoryService`，STM/LTM，检索与冲刷 |
| [heartbeat/README.md](./heartbeat/README.md) | `HeartbeatModule`、`TaskRunner` 与 `SchedulerEngine` 对接 |
| [life/README.md](./life/README.md) | `LifeManager`（账本 / 叙事 / `LifeService` 体验栈）与日终综合 |
| [persona/README.md](./persona/README.md) | `PersonaManager`，画像 / 偏好 / 情绪块 |

---

## 源码顶层

```
src/agent/soul/
├── presence/
│   ├── fsm/           # 当下态四维度 FSM
│   │   ├── affect/        # 情感
│   │   ├── somatic/       # 生理状态
│   │   ├── cognition/       # 认知（working_memory / thinking 自叙）
│   │   └── perception/    # 对环境的感知
│   ├── fsm/init/      # 起床 / 休眠（PresenceWakeEngine）
│   ├── interaction.py # 对话交互态（期待 / 冲动，非 FSM 维度）
│   ├── capture/       # 事件捕获：顶层注入 + Soul 内部演化
│   ├── transition/    # 纯期待 FSM 转移
│   └── gate/          # 限值 → SoulService → 顶层请求
├── memory/
├── heartbeat/
├── life/
└── persona/
```
