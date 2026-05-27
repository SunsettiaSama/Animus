# agent/soul/persona — 人格演化子系统

实现代码位于 **`src/agent/soul/persona/`**。`TaoLoop` 与 `SpeakService` 通过 `PersonaManager` / `PersonaService` 挂载画像与自我概念块。

本模块是 **「画像 + 体验 buffer + 慢变 self_concept」** 三层结构；快变情绪在 **`PresenceState.affect`**，不在 persona 域。

---

## 职责边界

| 域 | 职责 |
|---|---|
| **Persona** | 静态画像、体验聚类元数据、月度 self_concept 漂移 |
| **Presence** | 快变情绪、当下自叙 FSM |
| **Memory** | 对话事实记录与检索 |

---

## 目录结构

```
src/agent/soul/persona/
├── manager.py              # PersonaManager — TaoLoop / 内部主入口
├── service.py              # PersonaService — Soul dispatch 包装
├── builder.py              # ProfileBuilder（LLM 初始化画像）
├── profile/                # 静态画像
│   ├── profile.py          PersonaProfile
│   ├── block.py            ProfileBlock
│   └── store.py            ProfileStore → profile.json
├── buffer/                 # 体验聚类 + 月度漂移调度
│   ├── buffer.py           ExperienceBuffer
│   ├── store.py            ExperienceBufferStore
│   ├── clustering.py       主题聚类
│   ├── consolidation.py
│   └── drift_writer.py     MonthlyDriftUpdater
└── self_concept/           # 慢变自我叙事
    ├── concept.py          SelfConcept（信念分级 emerging → core）
    ├── block.py            SelfConceptBlock
    └── store.py            SelfConceptStore
```

---

## 架构总览

```
PersonaManager
       │
       ├── profile/       → ProfileStore → profile.json
       ├── buffer/       → ExperienceBufferStore → buffer 状态
       └── self_concept/ → SelfConceptStore → self_concept.json
```

- **profile**：静态身份描述，可经 `ProfileBuilder` LLM 初始化
- **buffer**：从 memory drift units 聚类主题，驱动月度 self_concept 更新
- **self_concept**：**仅**月度漂移写入；提供 `query_bias_keywords()` 供检索偏置

---

## Prompt 注入

`PersonaManager.all_blocks()` 顺序产出：

1. `ProfileBlock`
2. `SelfConceptBlock`（非空时）

Speak compose 层通过 `injected/persona/` 注入 persona 快照；Tao 通道经 `handlers/tao/blocks/` 注册块。

**L3 检索偏置**：`bias_query(query)` 将 self_concept 关键词附加到查询字符串。

---

## PersonaAction（Soul dispatch）

| Action | 说明 |
|---|---|
| `get_snapshot` | 完整 snapshot |
| `get_buffer` | buffer 状态 |
| `run_monthly_drift` | 月度 self_concept 漂移（重任务，orchestrator 异步） |
| `rebuild_profile` / `reload_profile` | 画像重建 |
| `portrait_revision` / `portrait_for_narrative` | 叙事用人像 |
| `reset_self_concept` | 重置自我概念 |

---

## API 摘录

```python
from agent.soul.persona import PersonaManager, PersonaService
from config.agent.persona_config import PersonaConfig

mgr = PersonaManager(cfg=PersonaConfig(enabled=True), llm=llm)
mgr.all_blocks()
mgr.bias_query(query)
mgr.snapshot()
```

---

## 持久化布局

```
.react/persona/
├── profile.json
├── self_concept.json
└── buffer/                  # ExperienceBufferStore 状态文件
```

---

## 相关文档

- [presence/README.md](../presence/README.md)（快变 affect）
- [memory/README.md](../memory/README.md)（drift units → buffer 聚类）
- [speak/README.md](../speak/README.md)（compose persona 注入）

历史文档 `docs/agent/react/persona/README.md` 保留为重定向。
