# agent/soul/persona — 人格演化子系统

实现代码位于 **`src/agent/soul/persona/`**。`TaoLoop` 通过 `from agent.soul.persona import PersonaManager` 挂载人格块与演化逻辑（配置仍为 `PersonaConfig`，目录仍默认指向 `.react/persona/`）。

本模块是一套 **「摘要 → 写入 → 注入」** 循环演化引擎，使人格、技能与自我认知随对话积累而变化。

**职责边界**

- **Persona**：身份演化——画像、风格、技能与自省文本。
- **Memory（React 侧）**：对话事实记录与蒸馏；与本模块分工明确。

---

## 目录结构

```
src/agent/soul/persona/
├── __init__.py            ← 统一导出公共符号（含 PersonaManager）
├── engine.py              ← EvolutionEngine — 顶层演化调度器
├── manager.py             ← PersonaManager — 对外唯一入口（TaoLoop 使用）
│
├── profile/               ← 人格子模块（身份是什么）
│   ├── profile.py         PersonaProfile
│   ├── skills.py          Skill + SkillsLibrary
│   ├── evolver.py         PersonaEvolver（LLM 增量）
│   ├── block.py           ProfileBlock / SkillsBlock / ReflectionBlock
│   └── store.py           ProfileStore
│
├── preference/            ← 偏好子模块（用户兴趣动态层）
│   ├── entry.py           PreferenceEntry
│   ├── recent.py          RecentPreference
│   ├── store.py           PreferenceStore
│   ├── block.py           PreferenceBlock
│   └── updater.py         PreferenceUpdater
│
└── emotional/             ← 叙事情感层
    ├── state.py           EmotionalAnchor + EmotionalState + EmotionalStateStore
    ├── evolver.py         EmotionalStateEvolver
    └── block.py           EmotionalStateBlock
```

---

## 架构总览

```
PersonaManager
       │
       ├── profile/     → ProfileStore → profile.json / skills.json / reflection.txt
       ├── preference/ → PreferenceStore → preference.json
       └── emotional/  → EmotionalStateStore → emotional_state.json
```

每轮对话结束后（`TaoLoop.post_process` 后台线程），在 `evolution_enabled` 且提供 LLM 时触发演化：`profile/skills`、`reflect`、`preference`、`emotional` 按各自间隔更新。

---

## Prompt 注入

`PersonaManager.all_blocks()` 顺序产出：`ProfileBlock`、`SkillsBlock`、`ReflectionBlock`、`PreferenceBlock`、`EmotionalStateBlock`（取决于 `PersonaConfig` 开关）。

**L3 检索偏置**：`bias_query(query)` 将近期偏好关键词附加到查询字符串。

---

## API 摘录

```python
from agent.soul.persona import PersonaManager
from config.agent.persona_config import PersonaConfig

mgr = PersonaManager(cfg=PersonaConfig(enabled=True), llm=llm)
mgr.all_blocks()
mgr.bias_query(query)
mgr.evolve(question, answer, steps)
```

---

## PersonaConfig

字段定义见 `config/agent/persona_config.py`；`persona_dir` 通常由 `TaoConfig._propagate_dirs()` 填为 `.react/persona`。

---

## 持久化布局

```
.react/persona/
├── profile.json
├── skills.json
├── reflection.txt
├── preference.json
└── emotional_state.json
```

---

历史文档路径 `docs/agent/react/persona/README.md` 保留为重定向；请以本文为准。
