# react — 完整链路文档

ReAct 框架的完整实现，由两层循环、五个子模块和一套配置体系构成。

---

## 目录结构

```
src/react/
├── loop.py              # ConvLoop — 外层多轮对话循环
├── tao.py               # TaoLoop  — 内层 TAO 推理循环 + 事件流
├── parser.py            # ReActOutputParser — LLM 输出解析
│
├── memory/              # 三层记忆系统（L1 短期 / L2 里程碑 / L3 长期）
│   ├── memory.py        # Step + Memory 基础数据结构
│   ├── processor.py     # MemoryProcessor — 统一入口（含 milestone）
│   ├── short_term/      # L1 短期：Token 滑动窗口
│   ├── medium_term/     # 中期蒸馏：LLM 提炼被驱逐步骤（过渡层）
│   ├── long_term/       # L3 长期：BGE Embedding + FAISS + RAG
│   │   ├── memory.py
│   │   ├── store.py     # LongTermStore（向量库 + 时间戳 + 持久化）
│   │   ├── init/        # make_memory 工厂函数
│   │   └── retrieve/    # Retriever + 五场景自动检索（含 TIMELINE）
│   └── milestone/       # L2 里程碑：重要事件，按需关键词检索
│       ├── entry.py     # MilestoneEntry 数据结构
│       ├── store.py     # MilestoneStore（JSON 持久化）
│       ├── retriever.py # MilestoneRetriever（关键词重叠匹配）
│       ├── scorer.py    # ImportanceScorer（LLM 重要性评估）
│       ├── memory.py    # MilestoneMemory 外观类
│       └── init.py      # make_milestone 工厂函数
│
├── prompt/              # Prompt 编排（块驱动）
│   ├── block.py         # PromptBlock 基类 + 5 个内置块
│   ├── manager.py       # PromptManager — 消息式组装 + 静态缓存
│   ├── builder.py       # PromptBuilder — 纯文本组装（辅助）
│   └── template.py      # ReActTemplate 中英预设
│
├── persona/             # 人格演化模块（"摘要-写入-注入"循环引擎）
│   ├── engine.py        # EvolutionEngine — 顶层演化调度器
│   ├── manager.py       # PersonaManager  — 对外唯一入口
│   ├── profile/         # 稳定层：人格画像 + 技能库 + 自省
│   │   ├── profile.py   #   PersonaProfile — 人物画像
│   │   ├── skills.py    #   Skill + SkillsLibrary — 行为技能库
│   │   ├── evolver.py   #   PersonaEvolver — LLM 演化器
│   │   ├── block.py     #   ProfileBlock / SkillsBlock / ReflectionBlock
│   │   └── store.py     #   ProfileStore（profile / skills / reflection）
│   ├── chronicle/       # 事件子模块：发生了什么
│   │   ├── chronicle.py #   ChronicleEntry + PersonaChronicle — 时序日志
│   │   ├── block.py     #   ChronicleBlock
│   │   └── store.py     #   ChronicleStore（chronicle.json）
│   └── preference/      # 动态层：短期偏好（情绪/话题兴趣/风格偏移）
│       ├── preference.py #  ShortTermPreference 数据结构
│       ├── updater.py   #   PreferenceUpdater（LLM 更新器）
│       └── block.py     #   PreferenceBlock（Prompt 注入块）
│
└── trace/               # 推理链存档
    └── store.py         # TraceStore — 写入 .react/traces/
```

---

## 两层循环结构

```
ConvLoop（多轮对话）
│  管理跨问题的会话历史，支持恢复
│
│  每次用户提问
│       │
│       ▼
│  TaoLoop.stream(question)
│       │
│       │  循环 max_steps 次
│       │       │
│       │       ├─ recall(include_long_term=(i==0)) → MemoryResult
│       │       ├─ build_messages / build_messages_from_static → list[BaseMessage]
│       │       ├─ LLM.stream()     → raw_output（流式）
│       │       ├─ parse()          → (thought, action, action_input)
│       │       │
│       │       ├─ [finish] → 存 _pending_finish，yield FinishEvent ← 先发送给客户端
│       │       └─ [tool]   → executor.run() → processor.add(Step)
│       │
│       ▼
│  FinishEvent.answer（客户端立即收到答案）
│
│  ← 后台 post_process() 在独立线程运行 →
│       commit + trace + persona + add_turn + consolidate?
│       + build_static() → _static_cache（下轮预热）
│
│  （下一个问题继续，直接使用 _static_cache 快速组装）
```

---

## TaoLoop 持有的组件（`__init__` 阶段构建）

| 组件 | 类型 | 生命周期 | 说明 |
|---|---|---|---|
| `_manager` | `PromptManager` | TaoLoop 级 | 管理 Prompt 组装和多轮历史 |
| `_long_term` | `LongTermMemory \| None` | TaoLoop 级（**单例**）| L3 FAISS 向量库，跨问题共享 |
| `_milestone` | `MilestoneMemory \| None` | TaoLoop 级（**单例**）| L2 里程碑，关键词检索，不自动全量注入 |
| `_trace_store` | `TraceStore \| None` | TaoLoop 级 | 推理链写入 `.react/traces/` |
| `_persona` | `PersonaManager \| None` | TaoLoop 级 | 人物画像 + 事件演化 + 短期偏好 |
| `_static_cache` | `StaticPromptParts \| None` | TaoLoop 级 | 上轮 post_process 预构建的静态 Prompt 部件 |
| `_pending_finish` | `_PendingFinish \| None` | 跨方法传递 | stream() 存入，post_process() 消费 |
| `processor` | `MemoryProcessor` | **每问题新建** | 三层记忆，接收注入的 long_term + milestone |

---

### 单步执行完整流程

### 非 finish 步骤

```
① 偏好偏置查询（L3 检索方向由上一轮短期偏好引导）
      recall_query = persona.bias_query(question)   ← 拼接话题兴趣关键词

② processor.recall(recall_query, include_long_term=(i==0))
      ├─ short_term  → list[Step]  （短期窗口内的完整步骤）
      ├─ medium_term → str         （被驱逐步骤的蒸馏结果）
      ├─ long_term   → str         （i==0 时执行 L3 FAISS 检索，后续步骤复用缓存）
      └─ milestone   → str         （i==0 时执行 L2 关键词检索，后续步骤复用缓存）

③ Prompt 组装（两条路径）
      # 合并 L3 与 L2 结果进同一个背景知识槽位
      lt_combined = long_term + "\n\n" + milestone

      有 _static_cache → manager.build_messages_from_static(cache, question, lt_combined, short_term)
                              ↳ system = cache.system_without_lt + lt_combined 块（注入槽位）
                              ↳ history = cache.history（快照）
      无 _static_cache → manager.build_messages(question, result(lt=lt_combined), extra_system_blocks=persona_blocks)
                              ↳ 完整渲染 system/persona/medium_term

      system_blocks（完整路径）:
        [SystemBlock]              ← ReAct 指令 + 工具列表（必有）
        [ProfileBlock]             ← 人物画像（persona 启用时）
        [ChronicleBlock]           ← 近期经历（persona 启用且有内容时）
        [SkillsBlock]              ← 技能库（skills_enabled 时）
        [ReflectionBlock]          ← 第一人称自省（reflection_enabled 且有内容时）
        [PreferenceBlock]          ← 短期偏好动态层（preference_enabled 且非 neutral 时）
        [MemoryBlock: lt_combined] ← L3 长期检索 + L2 里程碑（有内容时合并）
        [MemoryBlock: medium]      ← 蒸馏（有内容时）
      human_blocks:
        [QuestionBlock]          ← 问题前缀 + 问题（必有）
        [StepsBlock]             ← 当前轮 TAO 轨迹（有步骤时）
        [SuffixBlock]            ← "Thought:"（必有）
      → list[BaseMessage]

④ llm.stream_generate_messages(messages)
      → 流式产出 chunk，yield ChunkEvent
      → 拼成 raw_output

⑤ parse_llm_output(raw_output)
      → (thought, action, action_input)

⑥ executor.run({"action": action, "args": action_input})
      → observation（字符串）

⑦ processor.add(Step(thought, action, action_input, observation))
      ├─ _trace.append(step)           ← 完整链路，永不驱逐
      ├─ short.add(step)               → evicted: list[Step]
      └─ medium.absorb(evicted)
              ├─ _pending.extend(evicted)
              └─ len(_pending) >= distill_trigger_steps → _distill()
                       └─ LLM → 更新 _distillate，_pending 清空

⑧ yield StepEvent(...)
```

### finish 步骤（新的两阶段设计）

```
──── 阶段一：stream() 内（同步，用户等待这部分）────

self._pending_finish = _PendingFinish(question, answer, processor, persona_blocks)
yield FinishEvent(answer=answer)   ← 客户端立即收到答案，WebSocket 关闭

──── 阶段二：post_process()（后台线程，用户无感知）────

processor.commit(question, answer)
      ├─ medium.flush()                ← 强制蒸馏剩余 _pending
      ├─ long.add(Q + Steps + Distillate + A)
      │  long.save()                   ← 写 memories.json + FAISS 索引
      └─ milestone.try_add(question, answer, trace)
            ├─ LLM 评估重要性（0.0–1.0）
            └─ 若 >= threshold → milestone.save() → milestones.json

trace_store.write(question, answer, processor.trace)
      └─ 写 .react/traces/{timestamp}_{slug}.json

persona.evolve(question, answer, processor.trace)
      ├─ EvolutionEngine.run(...)
      │    ├─ ① chronicle  → 模板叙事追加（无 LLM，始终执行）
      │    ├─ ② profile    → LLM 分析 → ProfileDelta → traits/values/style 微更新
      │    │                 + LLM narrative 追加到 chronicle（每 evolve_interval 轮）
      │    ├─ ③ skills     → LLM 分析 → SkillDelta → 技能库增删改（同周期）
      │    └─ ④ reflect    → LLM 生成第一人称自省段落（每 reflect_interval 轮）
      └─ preference_updater.update(preference, question, answer)
               └─ LLM 分析对话 → 更新 mood / topic_interests / style_shifts
                  （每 preference_update_every_n 轮，不持久化，会话结束即重置）

manager.add_turn(question, answer)
      └─ _history 追加 [HumanMessage, AIMessage]

_maybe_consolidate()
      └─ turn_count % consolidation_k == 0 ?
              └─ manager.recent_turns(k) → long.add(会话窗口整合) → long.save()

self._static_cache = manager.build_static(          ← 预热下轮静态 Prompt
    medium_term=processor.medium_distillate,
    extra_system_blocks=persona_blocks,
)
```

---

## 静态 Prompt 缓存（`StaticPromptParts`）

每轮 `post_process()` 结束后，将**不依赖下一个问题**的 Prompt 部件预先渲染并缓存：

```python
@dataclass
class StaticPromptParts:
    system_without_lt: str       # base_system + persona + medium_term（无长期记忆块）
    history: list[BaseMessage]   # add_turn() 后的历史快照
```

下一轮问题到达时，只需：
1. 执行长期向量检索（唯一依赖查询的操作）
2. 将 `long_term` 文本注入 `system_without_lt`
3. 拼接 `question / short_term / suffix` 为 Human 消息

整个 Prompt 组装从"完整渲染"降为"字符串拼接"，减少 Prompt 延迟。

---

## 记忆子系统详解

### 三层对比

| 层级 | 名称 | 类 | 存储 | 自动注入 | 更新时机 |
|---|---|---|---|---|---|
| L1 | 短期 | `ShortTermMemory` | 内存 deque（token 滑动窗口）| ✅ 每步（Human 消息 StepsBlock）| 每步 |
| — | 中期蒸馏 | `MediumTermMemory` | 内存字符串（LLM 蒸馏）| ✅ 每问题（System MemoryBlock）| 驱逐时 |
| L2 | 里程碑 | `MilestoneMemory` | JSON 磁盘 + 关键词索引 | ❌ 按需检索（与 L3 合并注入）| 重要对话后异步 |
| L3 | 长期 | `LongTermMemory` | FAISS + JSON 磁盘 | ❌ 动态检索（System MemoryBlock）| 每次对话后异步 |

**中期蒸馏**是 L1→L3 的过渡层：被 L1 窗口驱逐的步骤先被 LLM 蒸馏成摘要，最终通过 `commit()` 写入 L3。

### L2 里程碑工作原理

L2 使用**关键词重叠匹配**（非向量检索）：

```
写入：commit() 后
  ImportanceScorer.score(Q, A, trace)
    ├─ LLM 评估重要性 0.0-1.0
    └─ >= threshold → MilestoneEntry(summary, detail, keywords, emotion, importance)
                        → MilestoneStore.add() → milestones.json

召回：i==0 时
  MilestoneRetriever.retrieve(entries, query, top_k)
    └─ 关键词集合重叠率排序 → 返回 top_k 条
         → 格式化为 "[DATE][emotion] summary" 追加到 lt_combined
```

### L3 长期记忆时序感知

所有检索结果均携带时间戳前缀 `[YYYY-MM-DD HH:MM UTC]`，LLM 可直接感知"这件事发生在什么时候"。检索支持五种模式：

| 模式 | 触发条件 | 说明 |
|---|---|---|
| LIGHT | 默认 | 每轮基础向量检索 |
| HEAVY | "之前/上次/记得…" | 增大 top_k，提高阈值 |
| SUPPLEMENT | 上下文过短 | 补充背景知识 |
| PROFILE | 会话首轮 | 检索用户档案 |
| TIMELINE | "最近/上周/recently…" | 按时间顺序返回最近 N 条（不走 FAISS）|

### MemoryProcessor 注入模式

```python
# TaoLoop 注入长期记忆 + 里程碑单例（推荐）
processor = MemoryProcessor(cfg, llm, long_term=self._long_term, milestone=self._milestone)

# 独立使用时自行创建（向后兼容）
processor = MemoryProcessor(cfg, llm)
```

---

## Prompt 子系统详解

### 块继承体系

```
PromptBlock (ABC)
  render() -> str | None    ← None 表示跳过此块
│
├── SystemBlock(text)              → ReAct 指令 + 工具列表
├── MemoryBlock(header, sep, content) → 长/中期记忆（空则跳过）
├── QuestionBlock(prefix, question)   → 当前问题
├── StepsBlock(format, steps)         → TAO 轨迹（空则跳过）
├── SuffixBlock(text)                 → "Thought:"
│
└── persona/（继承 PromptBlock）
    ├── ProfileBlock(profile)               → 人物画像
    ├── ChronicleBlock(chronicle, recent=N) → 最近 N 条经历
    ├── SkillsBlock(skills, top_k=5)        → 优先级最高的 K 条技能
    ├── ReflectionBlock(reflection)         → 第一人称自省（IROTE）
    └── PreferenceBlock(preference)         → 短期偏好动态层（非 neutral 时注入）
```

### 两条 build 路径

```
有 _static_cache（第 2 轮起）:
  build_messages_from_static(static, question, long_term, short_term)
    ├─ system = static.system_without_lt + [long_term 注入]
    ├─ history = static.history（快照，无需重新 add_turn）
    └─ human  = question + short_term steps + suffix

无 _static_cache（首轮或缓存失效）:
  build_messages(question, result, extra_system_blocks=persona_blocks)
    └─ 完整渲染所有块（同之前逻辑）
```

### 多轮历史

```
manager.add_turn(q, a)    →  _history.append([HumanMessage, AIMessage])
manager.recent_turns(k)   →  list[(question, answer)]  供 consolidate 使用
manager.turn_count         →  已记录轮数
manager.clear_history()   →  TaoLoop.reset() 时调用
```

---

## Persona 子系统详解

人格系统分为**稳定层**（长期人格）和**动态层**（短期偏好），由 `PersonaManager` 统一管理：

```
chronicle/store.py                profile/store.py
  chronicle.json                    profile.json / skills.json / reflection.txt
       │                                   │
PersonaChronicle                   PersonaProfile
  事件时序日志                        人物画像（可演化）
  ChronicleBlock                   SkillsLibrary
                                     技能库（可演化）
                                   reflection: str
                                     自省文本（定期刷新）
       │                                   │
       └─────────┬──────────────────────────┘
                 ▼
         EvolutionEngine.run()（稳定层演化）
           ① 模板叙事 → chronicle（每轮）
           ② LLM ProfileDelta → profile 微更新（每 N 轮）
           ③ LLM SkillDelta   → skills 增删改（每 N 轮）
           ④ LLM reflect      → reflection 刷新（每 M 轮）

         preference/（动态层，会话内有效）
           PreferenceUpdater.update(Q, A)
             └─ LLM 分析 → 更新 mood / topic_interests / style_shifts
                （不持久化；影响 L3 偏置查询；通过 PreferenceBlock 注入 Prompt）
                 │
         PersonaManager.all_blocks()
           → [ProfileBlock, ChronicleBlock, SkillsBlock?, ReflectionBlock?, PreferenceBlock?]
           → 注入 system prompt

         PersonaManager.bias_query(question)
           → question + " " + topic_interests   ← L3 检索偏置
```

### 稳定层 vs 动态层对比

| 维度 | 稳定层（长期人格）| 动态层（短期偏好）|
|---|---|---|
| 数据 | profile、skills、chronicle、reflection | mood、topic_interests、style_shifts |
| 更新 | LLM 每 N 轮演化（微更新）| LLM 每轮分析（全量替换）|
| 持久化 | ✅ 写入磁盘 | ❌ 仅内存，会话结束重置 |
| L3 影响 | 无直接影响 | 偏置检索查询 |
| Prompt 注入 | 始终注入 | 非 neutral 时注入 |

详细演化机制见 [persona/README.md](./persona/README.md)。

---

## Trace 子系统

```
TraceStore.write(question, answer, steps)
  └─ .react/traces/{YYYYMMDD_HHMMSS}_{slug}.json
       {
         "id": "uuid",
         "timestamp": "...",
         "question": "...",
         "answer": "...",
         "steps": [{ "index", "thought", "action", "action_input", "observation" }]
       }
```

`processor.trace` 返回本问题的完整推理链（所有非 finish 步骤），传递给 `trace_store.write`。

---

## ConvLoop：外层多轮管理

```python
ConvLoop(tao: TaoLoop)

# 新问题
conv.stream(question)   → 透传 tao.stream()

# 后台提交（在 WebSocket 关闭后异步调用）
conv.post_process()     → tao.post_process()

# 重置历史
conv.reset()            → tao.reset() → manager.clear_history() + 清空缓存

# 从保存的对话 JSON 恢复（页面重载后）
conv.restore(messages)
  └─ 逐对扫描 user/assistant → manager.add_turn()
     跳过空内容或乱序消息

conv.turn_count         → tao._manager.turn_count
```

---

## 关键数据契约

| 数据结构 | 定义位置 | 流转路径 |
|---|---|---|
| `Step` | `memory/memory.py` | tao → processor.add → short/medium → MemoryResult.short_term |
| `MemoryResult` | `memory/processor.py` | processor.recall → build_messages（含 milestone 字段）|
| `StaticPromptParts` | `prompt/manager.py` | post_process → _static_cache → build_messages_from_static |
| `list[BaseMessage]` | LangChain | build_messages → llm.stream_generate_messages |
| `TaoEvent` | `tao.py` | TaoLoop.stream → ConvLoop.stream → webui/调用方 |
| `MemoryEntry` | `memory/long_term/store.py` | LongTermStore.add → FAISS + memories.json |
| `MilestoneEntry` | `memory/milestone/entry.py` | ImportanceScorer.score → MilestoneStore.add → milestones.json |
| `ChronicleEntry` | `persona/chronicle/chronicle.py` | PersonaChronicle.append → chronicle.json |
| `ProfileDelta` | `persona/profile/evolver.py` | PersonaEvolver.evolve_profile → _apply_profile_delta |
| `SkillDelta` | `persona/profile/evolver.py` | PersonaEvolver.evolve_skills → _apply_skill_delta |
| `ShortTermPreference` | `persona/preference/preference.py` | PreferenceUpdater.update → PersonaManager._preference（内存）|

---

## 配置体系

```
TaoConfig
  ├── max_steps: int = 10
  ├── finish_action: str = "finish"
  ├── memory: MemoryConfig
  │     ├── short_term:  ShortTermMemoryConfig
  │     │     ├── enabled: bool = True
  │     │     ├── max_turns: int = 10
  │     │     └── max_tokens: int = 2048
  │     ├── medium_term: MediumTermMemoryConfig
  │     │     ├── enabled: bool = True
  │     │     ├── distill_trigger_steps: int = 4
  │     │     └── max_distillate_tokens: int = 400
  │     ├── long_term:   LongTermMemoryConfig       ← L3 向量检索
  │     │     ├── enabled: bool = False
  │     │     ├── load_from_disk: bool = False
  │     │     ├── memory_dir: str = ".react/memory"
  │     │     ├── top_k: int = 5
  │     │     ├── model_name_or_path: str = "BAAI/bge-small-zh-v1.5"
  │     │     ├── consolidation_k: int = 0   ← 0=禁用；N=每N轮合并一次
  │     │     └── retrieve: RetrieveConfig
  │     │           ├── light_top_k/min_score, heavy_top_k/min_score ...
  │     │           ├── timeline_top_k: int = 5   ← 时序召回条数
  │     │           └── profile_query: str = "用户习惯 偏好..."
  │     └── milestone:   MilestoneConfig             ← L2 里程碑
  │           ├── enabled: bool = False
  │           ├── milestone_dir: str = ".react/milestones"
  │           ├── max_milestones: int = 50
  │           ├── importance_threshold: float = 0.6
  │           ├── max_keywords: int = 5
  │           ├── top_k_retrieve: int = 2
  │           └── prompt_header: str = "## 重要里程碑"
  ├── prompt: PromptConfig
  │     └── lang: str = "en"   # "en" | "cn"
  ├── trace: TraceConfig
  │     ├── enabled: bool = True
  │     └── trace_dir: str = ".react/traces"
  └── persona: PersonaConfig
        ├── enabled: bool = False
        ├── persona_dir: str = ".react/persona"
        │   Chronicle（事件日志）
        ├── chronicle_enabled: bool = True
        ├── max_chronicle_entries: int = 100
        ├── max_chronicle_entry_chars: int = 200
        ├── max_chronicle_render_chars: int = 800
        ├── chronicle_recent_in_prompt: int = 5
        │   Profile（人物画像）
        ├── max_profile_chars: int = 500
        │   LLM 演化引擎
        ├── evolution_enabled: bool = False   ← 开启后接入 LLM 演化
        ├── evolve_interval: int = 1          ← 每 N 轮触发 profile + skills
        │   技能库
        ├── skills_enabled: bool = True
        ├── max_skills: int = 20
        ├── max_skills_in_prompt: int = 5
        ├── max_skills_chars: int = 600
        │   自省（IROTE）
        ├── reflection_enabled: bool = False
        ├── reflect_interval: int = 3
        ├── max_reflection_chars: int = 400
        │   短期偏好（动态层）
        ├── preference_enabled: bool = False
        ├── preference_update_every_n: int = 1  ← 每 N 轮更新一次
        └── max_preference_chars: int = 300
```

---

## 本地存储布局

```
.react/
├── history/              ← webui 对话历史（/api/history 管理）
│   └── {uuid}.json
├── memory/               ← L3 长期记忆（LongTermStore）
│   ├── memories.json
│   └── memory_index.faiss
├── milestones/           ← L2 里程碑（MilestoneStore）
│   └── milestones.json
├── persona/              ← 人格数据（稳定层）
│   ├── profile.json      ← PersonaProfile（ProfileStore）
│   ├── skills.json       ← SkillsLibrary（ProfileStore）
│   ├── chronicle.json    ← PersonaChronicle（ChronicleStore）
│   └── reflection.txt    ← 自省文本最新版（ProfileStore，每次覆写）
└── traces/               ← 推理链存档（TraceStore）
    └── {timestamp}_{slug}.json
```

> 短期偏好（`ShortTermPreference`）不持久化，仅存在于 `PersonaManager` 内存中，会话结束即重置。

---

## 子模块文档

- [prompt/README.md](./prompt/README.md) — Prompt 块架构详解
- [memory/README.md](./memory/README.md) — 三级记忆系统
- [action/README.md](./action/README.md) — 动作注册与执行
- [persona/README.md](./persona/README.md) — 人格演化引擎详解
