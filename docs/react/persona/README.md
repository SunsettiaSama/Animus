# persona — 人格演化子系统

本模块实现了一套**"摘要-写入-注入"循环演化引擎**，让 Agent 的人格、技能和自我认知随对话积累而动态变化。

**职责边界：**
- **Persona** — 负责 Agent 的身份演化：画像是谁、风格怎么变、技能怎么增长
- **Memory** — 负责对话事实的记录与蒸馏：发生了什么、讨论了什么

Chronicle（事件日志）已移除：它本质上是记录行为，属于 Memory 职责域，由 L2 中期记忆统一承担，避免与 Memory 系统重叠。

---

## 目录结构

```
persona/
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
┌─────────────────────────────────────────────────────────┐
│                      PersonaManager                      │
│  (外部唯一接口，TaoLoop 通过它读取 blocks / 触发演化)      │
└──────┬──────────────────────────────────────┬───────────┘
       │                                      │
       ▼                                      ▼
┌─────────────┐                    ┌──────────────────────┐
│  profile/   │                    │    preference/       │
│             │                    │                      │
│ PersonaProfile  ←── ProfileDelta │  RecentPreference    │
│ SkillsLibrary   ←── SkillDelta   │  (用户近期兴趣偏好)   │
│ reflection: str ←── reflect()    │                      │
│             │                    │  PreferenceStore     │
│ ProfileStore│                    └──────────────────────┘
└──────┬──────┘
       │
       ▼
   EvolutionEngine
  (调度：profile → skills → reflect)
       │
       ▼
  PersonaEvolver (LLM)
```

每轮对话结束后（`TaoLoop.post_process` 后台线程），演化引擎执行一次完整循环：

```
① profile    → LLM 分析交互 → 微更新   （每 evolve_interval 轮）
② skills     → LLM 分析交互 → 增删改   （每 evolve_interval 轮，与①同周期）
③ reflect    → LLM 生成自省段落        （每 reflect_interval 轮）
```

---

## 三大知识支柱

### 1. 人物画像 `PersonaProfile`

静态 + 可演化的 JSON 快照，描述 Agent "是谁"：

```python
@dataclass
class PersonaProfile:
    name:       str        # Agent 名称
    background: str        # 背景故事
    traits:     list[str]  # 性格特征（LLM 可增删）
    values:     list[str]  # 价值观   （LLM 可增删）
    style:      str        # 回复风格  （LLM 可替换）
```

`render()` 输出注入 Prompt 的文本块：
```
【人物画像】Alice
背景：...
性格：理性、专注、好奇
价值观：诚实、严谨
风格：简洁直接，擅用类比
```

持久化：`profile/store.py` → `.react/persona/profile.json`

---

### 2. 行为技能库 `SkillsLibrary`

存储 Agent 在不同情境下应如何行动的"行为手册"：

```python
@dataclass
class Skill:
    name:        str   # 技能名称，全局唯一 ID
    description: str   # 具体行为描述
    trigger:     str   # 触发条件（可选）
    priority:    int   # 1-10，注入 Prompt 时按此排序
```

`render(top_k=5)` 输出注入 Prompt 的技能块：
```
【行为技能库】
▸ [深度追问] 当问题有多个可能解读时，先列举假设再逐一排查  (触发条件：问题模糊或含歧义)
▸ [共情回应] 当用户表达情绪时优先共情，不急于给出解决方案
...
```

持久化：`profile/store.py` → `.react/persona/skills.json`

---

### 3. 近期偏好 `RecentPreference`

动态记录用户近期感兴趣的话题，用于两个目的：

- **L3 检索偏置**：`bias_query(query)` 将偏好关键词附加到查询，引导长期记忆向量检索
- **Prompt 注入**（可选）：`PreferenceBlock` 提示 Agent 关注用户当前兴趣点

持久化：`preference/store.py` → `.react/persona/preference.json`

---

## 演化引擎详解

### 演化触发时机

```
TaoLoop.stream(question)
  └─ yield FinishEvent  ←── 用户立即收到答案

TaoLoop.post_process()  ←── 后台线程，用户无感知
  └─ persona.evolve(question, answer, steps)
        └─ engine.run(...)
```

所有 LLM 调用均在后台线程，不影响用户响应延迟。

---

### 第①步：Profile 演化（每 `evolve_interval` 轮，需 LLM）

`PersonaEvolver.evolve_profile()` 将当前交互送给 LLM，要求输出 `ProfileDelta`：

**LLM System Prompt（核心约束）：**
> 变化必须非常细微，大多数字段应为空列表或空字符串；每次最多允许 1-2 个特征发生轻微改变。

**LLM 输入（Human 消息）：**
```
当前人格状态：
【人物画像】Alice
...

本次交互：
- 问题：{question}
- 使用方式：{tools used}
- 回答摘要：{answer[:150]}

请分析这次交互对人格的细微影响，输出 JSON：
```

**LLM 输出（`ProfileDelta` 结构）：**
```json
{
  "narrative":      "（描述这段经历，50字以内）",
  "traits_add":     [],
  "traits_remove":  [],
  "values_add":     [],
  "values_remove":  [],
  "style_hint":     "",
  "mood":           "略感好奇",
  "growth_note":    ""
}
```

**应用规则（`_apply_profile_delta`）：**
- `traits_add`    → 去重后追加到 `profile.traits`
- `traits_remove` → 从 `profile.traits` 中移除
- `values_add/remove` → 同上
- `style_hint`    → 非空时替换 `profile.style`

---

### 第②步：Skills 演化（与①同周期，需 LLM）

`PersonaEvolver.evolve_skills()` 分析本次交互是否应更新技能库：

**LLM 输入包含：**
- 当前人格画像
- 当前全量技能库（纯文本）
- 本次交互摘要（问题 + 工具 + 回答前120字）

**LLM 输出（`SkillDelta` 结构）：**
```json
{
  "add": [
    {"name": "...", "description": "...", "trigger": "...", "priority": 5}
  ],
  "update": [
    {"name": "已有技能名", "description": "新描述", "priority": 7}
  ],
  "remove": ["过时的技能名"]
}
```

**约束（System Prompt）：**
> 优先考虑"不变化"，除非有充分理由；新增技能的 priority 在 3-8 之间。

**应用规则（`_apply_skill_delta`）：**
- `add`    → `SkillsLibrary.add()`（同名技能会被替换，超出 max_skills 则按 priority 淘汰）
- `update` → `SkillsLibrary.update_skill(name, **kwargs)`
- `remove` → `SkillsLibrary.remove(name)`

---

### 第③步：Self-Reflection 自省（每 `reflect_interval` 轮，需 LLM）

基于 IROTE 机制，生成 Agent 对自身当前状态的第一人称感知：

**LLM 输入包含：**
- 人格画像（`profile.render()`）
- 当前技能库（`skills.render(top_k=5)`）

**LLM 输出（纯文本，60-150字）：**
```
我最近在处理技术问题时越来越倾向于先建立框架再填充细节，
这种习惯在面对复杂系统时让我感到更从容。
```

此文本作为 `ReflectionBlock` 注入每次 Prompt 的系统消息末尾。

---

## Prompt 注入方式

`PersonaManager.all_blocks()` 按顺序返回所有启用的块：

```
[ProfileBlock]         ← 人物画像（始终注入）
[SkillsBlock]          ← 技能库（skills_enabled=True 时注入）
[ReflectionBlock]      ← 自省（reflection_enabled=True 且有内容时注入）
[PreferenceBlock]      ← 近期偏好（preference_enabled=True 且有内容时注入）
```

这些块作为 `extra_system_blocks` 传入 `PromptManager.build_messages()`，拼接在 ReAct 指令之后、记忆块之前：

```
[系统消息]
ReAct 指令 + 工具列表
---
【人物画像】Alice
背景：... 性格：... 价值观：... 风格：...
---
【行为技能库】
▸ [深度追问] ...
---
【自我感知】
我最近在处理技术问题时...
---
（长期记忆 / 中期蒸馏）
```

---

## PersonaManager API

```python
mgr = PersonaManager(cfg: PersonaConfig, llm: LLM | None = None)

# 属性
mgr.profile           → PersonaProfile
mgr.skills            → SkillsLibrary
mgr.reflection        → str
mgr.recent_preference → RecentPreference

# PromptBlock 构建
mgr.profile_block()    → ProfileBlock
mgr.skills_block()     → SkillsBlock
mgr.reflection_block() → ReflectionBlock
mgr.preference_block() → PreferenceBlock
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
    enabled:     bool = False        # 总开关；False 时 TaoLoop 不创建 PersonaManager
    persona_dir: str  = ""

    # ── Profile ────────────────────────────────────────────────────
    max_profile_chars:   int = 500   # ProfileBlock 渲染截断；0 不限

    # ── LLM 演化引擎 ──────────────────────────────────────────────
    evolution_enabled:  bool = False  # 开启 LLM 演化（需要 llm 参数）
    evolve_interval:    int  = 1      # 每 N 轮触发 profile + skills 演化

    # ── 技能库 ────────────────────────────────────────────────────
    skills_enabled:       bool = True  # 技能注入（含 LLM 更新，需 evolution_enabled）
    max_skills:           int  = 50    # 技能库容量上限
    max_skills_in_prompt: int  = 5     # 注入 Prompt 的最高优先级技能条数
    max_skills_chars:     int  = 600   # SkillsBlock 渲染截断；0 不限

    # ── 自省（IROTE） ─────────────────────────────────────────────
    reflection_enabled:   bool = False  # 开启自省注入（需 evolution_enabled）
    reflect_interval:     int  = 3      # 每 N 轮重新生成自省
    max_reflection_chars: int  = 400    # ReflectionBlock 渲染截断；0 不限

    # ── 近期偏好 ──────────────────────────────────────────────────
    preference_enabled:       bool = True  # 偏好追踪与 L3 检索偏置
    preference_window_days:   int  = 30    # 偏好有效期（天）
    max_preference_topics:    int  = 10    # 最多保留话题数
    max_preference_chars:     int  = 400   # PreferenceBlock 渲染截断
    preference_update_every_n: int = 3     # 每 N 轮更新一次偏好
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
| 完整 LLM 演化  | ✓ | ✓ | ✓ | ✗ | profile + skills |
| 自省注入       | ✓ | ✓ | ✓ | ✓ | + reflect |
