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
├── memory/
├── heartbeat/
├── life/
└── persona/
```
