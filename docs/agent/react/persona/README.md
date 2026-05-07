# agent/react/persona — 人格演化子系统

本模块实现了一套**"摘要-写入-注入"循环演化引擎**，让 Agent 的人格、技能和自我认知随对话积累而动态变化。

**职责边界：**
- **Persona** — 负责 Agent 的身份演化：画像是谁、风格怎么变、技能怎么增长
- **Memory** — 负责对话事实的记录与蒸馏：发生了什么、讨论了什么

---

## 目录结构

```
src/agent/react/persona/
├── __init__.py            ← 统一导出所有公共符号
├── engine.py              ← EvolutionEngine — 顶层演化调度器
├── manager.py             ← PersonaManager  — 对外唯一入口
│
├── profile/               ← 人格子模块（身份是什么）
│   ├── __init__.py
│   ├── profile.py         PersonaProfile — 人物画像数据结构
│   ├── skills.py          Skill + SkillsLibrary — 行为技能库
│   ├── evolver.py         PersonaEvolver — LLM 演化器（三层）
│   ├── block.py           ProfileBlock / SkillsBlock / ReflectionBlock
│   └── store.py           ProfileStore — profile.json / skills.json / reflection.txt
│
└── preference/            ← 偏好子模块（用户兴趣动态层）
    ├── __init__.py
    ├── entry.py           PreferenceEntry — 单条兴趣记录
    ├── recent.py          RecentPreference — 近期偏好聚合
    ├── store.py           PreferenceStore — preference.json
    ├── block.py           PreferenceBlock
    └── updater.py         PreferenceUpdater — LLM 驱动更新
```

---

## 架构总览

```
PersonaManager（外部唯一接口）
       │
       ├─── profile/
       │      PersonaProfile（画像）← ProfileDelta（LLM）
       │      SkillsLibrary（技能）← SkillDelta（LLM）
       │      reflection: str     ← reflect()（LLM）
       │      ProfileStore → profile.json / skills.json / reflection.txt
       │
       └─── preference/（动态层）
              RecentPreference（用户近期兴趣偏好）
              PreferenceStore → preference.json
```

每轮对话结束后（`TaoLoop.post_process` 后台线程），演化引擎执行：

```
① profile + skills → LLM 分析交互 → 微更新   （每 evolve_interval 轮）
② reflect          → LLM 生成自省段落        （每 reflect_interval 轮）
③ preference       → LLM 生成快照 → 更新偏好  （每 preference_update_every_n 轮）
```

---

## 三大知识支柱

### 1. 人物画像 `PersonaProfile`

```python
@dataclass
class PersonaProfile:
    name:       str        # Agent 名称
    background: str        # 背景故事
    traits:     list[str]  # 性格特征（LLM 可增删）
    values:     list[str]  # 价值观（LLM 可增删）
    style:      str        # 回复风格（LLM 可替换）
```

持久化：`ProfileStore` → `.react/persona/profile.json`

### 2. 行为技能库 `SkillsLibrary`

```python
@dataclass
class Skill:
    name:        str   # 技能名称，全局唯一 ID
    description: str   # 具体行为描述
    trigger:     str   # 触发条件（可选）
    priority:    int   # 1-10，注入 Prompt 时按此排序
```

持久化：`ProfileStore` → `.react/persona/skills.json`

### 3. 近期偏好 `RecentPreference`

动态记录用户近期感兴趣的话题：

- **L3 检索偏置**：`bias_query(query)` 将偏好关键词附加到查询，引导长期记忆向量检索
- **Prompt 注入**（可选）：`PreferenceBlock` 提示 Agent 关注用户当前兴趣点

持久化：`PreferenceStore` → `.react/persona/preference.json`

---

## 演化引擎详解

### Profile + Skills 演化（每 `evolve_interval` 轮）

`PersonaEvolver.evolve_profile()` → 输出 `ProfileDelta`：
```json
{"traits_add": [], "traits_remove": [], "values_add": [], "values_remove": [], "style_hint": ""}
```

`PersonaEvolver.evolve_skills()` → 输出 `SkillDelta`：
```json
{"add": [{"name": "...", "description": "...", "trigger": "...", "priority": 5}], "update": [], "remove": []}
```

约束：变化必须非常细微，大多数情况应返回空列表。

### Self-Reflection 自省（每 `reflect_interval` 轮）

基于 IROTE 机制，生成 Agent 第一人称感知文本（60-150字），作为 `ReflectionBlock` 注入系统提示末尾。

---

## Prompt 注入方式

`PersonaManager.all_blocks()` 按顺序返回所有启用的块：

```
[ProfileBlock]         ← 人物画像（始终注入）
[SkillsBlock]          ← 技能库（skills_enabled=True 时注入）
[ReflectionBlock]      ← 自省（reflection_enabled=True 且有内容时注入）
[PreferenceBlock]      ← 近期偏好（preference_enabled=True 且有内容时注入）
```

---

## PersonaManager API

```python
from agent.react.persona import PersonaManager
from config.agent.persona_config import PersonaConfig

mgr = PersonaManager(cfg=PersonaConfig(enabled=True), llm=llm)

# PromptBlock 构建
mgr.all_blocks()       → list[PromptBlock]   ← TaoLoop 调用此方法

# L3 检索偏置
mgr.bias_query(query)  → str   ← 附加近期偏好关键词

# 演化驱动（每轮 post_process 中调用）
mgr.evolve(question, answer, steps)
```

`evolution_enabled=False` 或 `llm=None` 时，`evolve()` 不执行任何 LLM 调用。

---

## PersonaConfig 完整字段

```python
@dataclass
class PersonaConfig:
    enabled:     bool = False        # 总开关
    persona_dir: str  = ""           # 由 TaoConfig._propagate_dirs 自动填充

    max_profile_chars:    int = 500  # ProfileBlock 渲染截断

    evolution_enabled:    bool = False   # 开启 LLM 演化
    evolve_interval:      int  = 1       # 每 N 轮触发 profile + skills 演化

    skills_enabled:       bool = True
    max_skills:           int  = 50
    max_skills_in_prompt: int  = 5
    max_skills_chars:     int  = 600

    reflection_enabled:   bool = False
    reflect_interval:     int  = 3
    max_reflection_chars: int  = 400

    preference_enabled:        bool = True
    preference_window_days:    int  = 30
    max_preference_topics:     int  = 10
    max_preference_chars:      int  = 400
    preference_update_every_n: int  = 3
```

---

## 持久化布局

```
.react/persona/
├── profile.json       ← PersonaProfile（手动编辑 + LLM 增量更新）
├── skills.json        ← SkillsLibrary（LLM 增删改维护）
├── reflection.txt     ← 最新自省文本（每次 reflect 覆写）
└── preference.json    ← 近期偏好（滚动更新）
```

---

## 演化开关矩阵

| 场景 | `enabled` | `evolution_enabled` | `skills_enabled` | `reflection_enabled` | LLM 调用 |
|------|:---------:|:-------------------:|:----------------:|:--------------------:|:--------:|
| 纯静态画像注入 | ✓ | ✗ | ✗ | ✗ | 无 |
| 静态画像 + 技能 | ✓ | ✗ | ✓ | ✗ | 无 |
| 完整 LLM 演化 | ✓ | ✓ | ✓ | ✗ | profile + skills |
| 自省注入 | ✓ | ✓ | ✓ | ✓ | + reflect |
