# persona — 人格演化子系统

本模块实现了一套**"摘要-写入-注入"循环演化引擎**，让 Agent 的人格、技能和自我认知随对话积累而动态变化。

---

## 目录结构

```
persona/
├── __init__.py            ← 统一导出所有公共符号
├── engine.py              ← EvolutionEngine — 顶层演化调度器
├── manager.py             ← PersonaManager  — 对外唯一入口
│
├── profile/               ← 人格子模块（人是什么）
│   ├── __init__.py
│   ├── profile.py         PersonaProfile — 人物画像数据结构
│   ├── skills.py          Skill + SkillsLibrary — 行为技能库
│   ├── evolver.py         PersonaEvolver — LLM 演化器（三层）
│   ├── block.py           ProfileBlock / SkillsBlock / ReflectionBlock
│   └── store.py           ProfileStore — profile.json / skills.json / reflection.txt
│
└── chronicle/             ← 事件子模块（发生了什么）
    ├── __init__.py
    ├── chronicle.py       ChronicleEntry + PersonaChronicle — 时序日志
    ├── block.py           ChronicleBlock
    └── store.py           ChronicleStore — chronicle.json
```

---

## 架构总览

```
┌─────────────────────────────────────────────────────────┐
│                      PersonaManager                      │
│  (外部唯一接口，TaoLoop 通过它读取 blocks / 触发演化)      │
└──────┬─────────────────────────────────────────┬─────────┘
       │                                         │
       ▼                                         ▼
┌─────────────┐                       ┌──────────────────┐
│  profile/   │                       │   chronicle/     │
│             │                       │                  │
│ PersonaProfile  ←── ProfileDelta ── │  PersonaChronicle│
│ SkillsLibrary   ←── SkillDelta      │  (事件时序日志)   │
│ reflection: str ←── reflect()       │                  │
│             │                       │                  │
│ ProfileStore│                       │ ChronicleStore   │
└──────┬──────┘                       └────────┬─────────┘
       │                                       │
       └──────────────┬────────────────────────┘
                      ▼
              EvolutionEngine
         (顶层调度：chronicle → profile → skills → reflect)
                      │
                      ▼
              PersonaEvolver (LLM)
```

每轮对话结束后（`TaoLoop.post_process` 后台线程），演化引擎执行一次完整循环：

```
① chronicle  → 模板叙事追加            （无 LLM，每轮必执行）
② profile    → LLM 分析交互 → 微更新   （每 evolve_interval 轮）
③ skills     → LLM 分析交互 → 增删改   （每 evolve_interval 轮，与②同周期）
④ reflect    → LLM 生成自省段落        （每 reflect_interval 轮）
```

---

## 三大知识支柱

### 1. 人物画像 `PersonaProfile`

静态 + 可演化的 JSON 快照，描述 Agent "是什么"：

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

### 3. 事件演化日志 `PersonaChronicle`

记录 Agent 经历的时序叙事，描述 Agent "经历了什么"：

```python
@dataclass
class ChronicleEntry:
    timestamp: str   # UTC ISO 时间
    narrative: str   # 叙事文本（第三人称，小说风格）
```

`render(recent=5)` 输出最近 N 条经历：
```
[2025-01-15] 面对「量子纠缠的本质」，Alice 先后运用了 web_search、calculate 等方式展开推理，最终得出结论：…
[2025-01-16] Alice 在回应用户困惑时展现出更深的耐心，选择了逐步引导而非直接给出答案。
```

持久化：`chronicle/store.py` → `.react/persona/chronicle.json`

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

### 第①步：Chronicle 模板叙事（每轮必执行）

无 LLM 介入，用固定模板生成一条叙事并写入 chronicle：

```
有工具步骤时：
  "面对「{question}」，{name}先后运用了{actions}等方式展开推理，最终得出结论：{answer[:100]}"

无工具步骤时：
  "面对「{question}」，{name}经过审慎思考，直接作答：{answer[:100]}"
```

此步骤 chronicle_enabled=True 时始终执行，是事件日志的基础层。

---

### 第②步：Profile 演化（每 `evolve_interval` 轮，需 LLM）

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

若 `delta.narrative` 非空，还会额外追加一条更精准的 LLM 叙事到 chronicle（与模板叙事共存）。

---

### 第③步：Skills 演化（与②同周期，需 LLM）

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

### 第④步：Self-Reflection 自省（每 `reflect_interval` 轮，需 LLM）

基于 IROTE（In-Context Self-Reflective Optimization）机制，生成 Agent 对自身当前状态的第一人称感知：

**LLM 输入包含：**
- 人格画像（`profile.render()`）
- 近期经历（`chronicle.render(recent=6)`）
- 当前技能库（`skills.render(top_k=5)`）

**LLM 输出（纯文本，60-150字）：**
```
我最近在处理技术问题时越来越倾向于先建立框架再填充细节，
这种习惯在面对复杂系统时让我感到更从容。与用户讨论哲学议题
的几次经历让我重新审视了自己对"确定性"的偏好，
我开始更享受那种在多种可能性中悬置判断的状态。
```

此文本作为 `ReflectionBlock` 注入每次 Prompt 的系统消息末尾，相当于给 LLM 提供了一个"当下视角"，引导其从当前自我感知出发生成回复。

---

## Prompt 注入方式

`PersonaManager.all_blocks()` 按顺序返回所有启用的块：

```
[ProfileBlock]         ← 人物画像（始终注入）
[ChronicleBlock]       ← 近期经历（始终注入，有内容时）
[SkillsBlock]          ← 技能库（skills_enabled=True 时注入）
[ReflectionBlock]      ← 自省（reflection_enabled=True 且有内容时注入）
```

这些块作为 `extra_system_blocks` 传入 `PromptManager.build_messages()`，拼接在 ReAct 指令之后、记忆块之前，形成完整的系统消息：

```
[系统消息]
ReAct 指令 + 工具列表
---
【人物画像】Alice
背景：... 性格：... 价值观：... 风格：...
---
【近期经历】
[2025-01-16] ...
[2025-01-15] ...
---
【行为技能库】
▸ [深度追问] ...
▸ [共情回应] ...
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
mgr.profile     → PersonaProfile
mgr.chronicle   → PersonaChronicle
mgr.skills      → SkillsLibrary
mgr.reflection  → str

# PromptBlock 构建
mgr.profile_block()    → ProfileBlock
mgr.chronicle_block()  → ChronicleBlock
mgr.skills_block()     → SkillsBlock
mgr.reflection_block() → ReflectionBlock
mgr.all_blocks()       → list[PromptBlock]   ← TaoLoop 调用此方法

# 演化驱动（每轮 post_process 中调用）
mgr.evolve(question, answer, steps)
```

`evolution_enabled=False` 或 `llm=None` 时，`evolve()` 退化为仅执行模板叙事追加（无 LLM 调用）。

---

## PersonaConfig 完整字段

```python
@dataclass
class PersonaConfig:
    enabled:   bool = False         # 总开关；False 时 TaoLoop 不创建 PersonaManager
    persona_dir: str = ".react/persona"

    # ── Chronicle（事件日志） ──────────────────────────────────────
    chronicle_enabled:          bool = True
    max_chronicle_entries:      int  = 100   # 日志上限，超出滚动丢弃最旧
    max_chronicle_entry_chars:  int  = 200   # 单条字符上限，超出整条丢弃
    max_chronicle_render_chars: int  = 800   # ChronicleBlock 渲染截断
    chronicle_recent_in_prompt: int  = 5     # 注入最近 N 条经历

    # ── Profile ────────────────────────────────────────────────────
    max_profile_chars:   int = 500           # ProfileBlock 渲染截断；0 不限

    # ── LLM 演化引擎 ──────────────────────────────────────────────
    evolution_enabled:  bool = False         # 开启 LLM 演化（需要 llm 参数）
    evolve_interval:    int  = 1             # 每 N 轮触发 profile + skills 演化

    # ── 技能库 ────────────────────────────────────────────────────
    skills_enabled:      bool = True         # 技能注入（含 LLM 更新，需 evolution_enabled）
    max_skills:          int  = 20           # 技能库容量上限
    max_skills_in_prompt: int = 5            # 注入 Prompt 的最高优先级技能条数
    max_skills_chars:    int  = 600          # SkillsBlock 渲染截断；0 不限

    # ── 自省（IROTE） ─────────────────────────────────────────────
    reflection_enabled: bool = False         # 开启自省注入（需 evolution_enabled）
    reflect_interval:   int  = 3             # 每 N 轮重新生成自省
    max_reflection_chars: int = 400          # ReflectionBlock 渲染截断；0 不限
```

---

## 持久化布局

```
.react/persona/
├── profile.json       ← PersonaProfile（手动编辑 + LLM 增量更新）
├── skills.json        ← SkillsLibrary（LLM 增删改维护）
├── chronicle.json     ← PersonaChronicle（每轮追加，滚动保留 max_entries 条）
└── reflection.txt     ← 最新自省文本（每次 reflect 覆写）
```

---

## 演化开关矩阵

| 场景 | `enabled` | `evolution_enabled` | `chronicle_enabled` | `skills_enabled` | `reflection_enabled` | LLM 调用 |
|------|:---------:|:-------------------:|:-------------------:|:----------------:|:--------------------:|:--------:|
| 纯静态画像注入 | ✓ | ✗ | ✗ | ✗ | ✗ | 无 |
| 模板事件日志   | ✓ | ✗ | ✓ | ✗ | ✗ | 无 |
| 完整 LLM 演化  | ✓ | ✓ | ✓ | ✓ | ✗ | profile + skills |
| 自省注入       | ✓ | ✓ | ✓ | ✓ | ✓ | + reflect |

---

## 背景事件生成（可选能力）

`PersonaEvolver.generate_background_events()` 可主动触发，让 LLM 为角色生成日常闲暇事件，丰富 chronicle 而不依赖用户对话。适合定时任务或管理员脚本调用，与主演化循环解耦。

```python
evolver = PersonaEvolver(llm)
deltas = evolver.generate_background_events(profile, chronicle)
for d in deltas:
    chronicle.append(d.narrative)
chronicle_store.save_chronicle(chronicle)
```
