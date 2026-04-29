# react 模块

ReAct（Reasoning + Acting）核心框架，实现两层循环结构、四层记忆系统、块驱动 Prompt 组装、人格演化引擎和推理链存档。

---

## 目录结构

```
src/react/
├── loop.py              # ConvLoop — 外层多轮对话循环
├── tao.py               # TaoLoop  — 内层 TAO 推理循环 + 事件流
├── parser.py            # ReActOutputParser / LLM 输出解析
│
├── memory/              # 四层记忆系统（L1 短期 / 中期蒸馏 / L2 里程碑 / L3 长期）
│   ├── memory.py        # Step + Memory 基础数据结构
│   ├── processor.py     # MemoryProcessor：统一读写接口（含 milestone）
│   ├── short_term/      # L1 短期（Token 滑动窗口）
│   ├── medium_term/     # 中期蒸馏（LLM 压缩被驱逐步骤）
│   ├── long_term/       # L3 长期（BGE Embedding + FAISS + RAG）
│   │   ├── memory.py
│   │   ├── store.py     # LongTermStore（向量 + 时间戳 + 持久化）
│   │   ├── init/        # make_memory 工厂函数
│   │   └── retrieve/    # Retriever + 五场景检索模式（含 TIMELINE）
│   └── milestone/       # L2 里程碑（重要事件，关键词检索）
│       ├── entry.py     # MilestoneEntry 数据类
│       ├── store.py     # MilestoneStore（JSON 持久化）
│       ├── retriever.py # MilestoneRetriever（关键词匹配 + jieba 可选）
│       ├── scorer.py    # ImportanceScorer（LLM 评分 0.0–1.0）
│       ├── memory.py    # MilestoneMemory 门面
│       └── init.py      # make_milestone 工厂函数
│
├── prompt/              # Prompt 块驱动组装系统
│   ├── block.py         # PromptBlock 基类 + 5 种内置块
│   ├── manager.py       # PromptManager：Prompt 构建 + 静态缓存
│   ├── builder.py       # PromptBuilder：消息组装底层
│   ├── parser.py        # ReActOutputParser + ParseQuality 枚举
│   ├── repair.py        # Prompt 修复（输出格式错误时重试）
│   └── template.py      # ReActTemplate 语言模板
│
├── persona/             # 人格演化系统（"知识-技能-反省"三层 + 近期偏好）
│   ├── engine.py        # EvolutionEngine：LLM 驱动演化
│   ├── manager.py       # PersonaManager：统一接口
│   ├── profile/         # 稳定层（画像 + 技能库 + 自省）
│   │   ├── profile.py   #   PersonaProfile 数据类
│   │   ├── skills.py    #   Skill + SkillsLibrary
│   │   ├── evolver.py   #   PersonaEvolver（LLM 增量更新）
│   │   ├── block.py     #   ProfileBlock / SkillsBlock / ReflectionBlock
│   │   └── store.py     #   ProfileStore（profile / skills / reflection）
│   └── preference/      # 动态层（情绪 / 话题兴趣 / 风格偏移）
│       ├── entry.py     #   PreferenceEntry 快照
│       ├── store.py     #   PreferenceStore（preference.json）
│       ├── updater.py   #   PreferenceUpdater（LLM 生成快照）
│       ├── block.py     #   PreferenceBlock（Prompt 注入）
│       └── recent.py    #   RecentPreference（k 天滑动窗口聚合）
│
└── trace/               # 推理链存档
    └── store.py         # TraceStore：写入 .react/traces/
```

---

## 整体流程

```
ConvLoop（多轮会话管理）
   │  接收用户输入，管理对话历史
   │
   ▼
TaoLoop.stream(question)
   │
   │  循环 max_steps 次
   │     ├─ recall(include_long_term=(i==0))  → MemoryResult
   │     ├─ build_messages(...)               → list[BaseMessage]
   │     ├─ LLM.stream()                      → raw_output（流式 chunk）
   │     ├─ parse()                           → (thought, action, action_input)
   │     │
   │     ├─ [finish] → yield FinishEvent → 客户端立即收到答案
   │     └─ [tool]   → executor.run() → processor.add(Step)
   │
   FinishEvent.answer 发送完毕，WebSocket 关闭
   │
   └─ post_process()（后台线程，用户无感知）
         commit + trace + persona + add_turn + consolidate
         + build_static() → _static_cache（预热下轮）
```

---

## TaoLoop 核心属性

| 属性 | 类型 | 来源 | 说明 |
|---|---|---|---|
| `_manager` | `PromptManager` | TaoLoop 内部 | 负责 Prompt 构建与历史管理 |
| `_long_term` | `LongTermMemory \| None` | TaoLoop 内部（可选）| L3 FAISS 向量存储与检索 |
| `_milestone` | `MilestoneMemory \| None` | TaoLoop 内部（可选）| L2 里程碑事件检索与评分 |
| `_trace_store` | `TraceStore \| None` | TaoLoop 内部 | 写入推理链到 `.react/traces/` |
| `_persona` | `PersonaManager \| None` | TaoLoop 内部 | 人格注入 + 演化 + 偏置 |
| `_static_cache` | `StaticPromptParts \| None` | TaoLoop 内部 | `post_process` 预热的静态 Prompt 片段 |
| `_pending_finish` | `_PendingFinish \| None` | 临时状态 | `stream()` 末尾，`post_process()` 消费 |
| `processor` | `MemoryProcessor` | **外部传入** | 统一读写 short_term + long_term + milestone |

---

## 单步推理流程（stream 内循环）

```
1. 偏置查询向量（L3 检索方向）
   recall_query = persona.bias_query(question)   ← 融合近期话题偏好

2. processor.recall(recall_query, include_long_term=(i==0))
      → short_term  : list[Step]  （当前 session 推理步骤）
      → medium_term : str         （被驱逐步骤的 LLM 摘要）
      → long_term   : str         （仅首步检索 L3 FAISS 向量结果）
      → milestone   : str         （仅首步检索 L2 关键词匹配结果）

3. Prompt 构建（system blocks）
   system_blocks:
     [SystemBlock]              → ReAct 系统提示 + 工具描述
     [ProfileBlock]             → 人物画像（persona 启用时）
     [SkillsBlock]              → 技能列表（skills_enabled 时）
     [ReflectionBlock]          → 自省文本（reflection_enabled 且非空时）
     [PreferenceBlock]          → 近期偏好（preference_enabled 且非 neutral 时）
     [MemoryBlock: lt_combined] → L3 向量结果 + L2 里程碑（拼接后注入）
     [MemoryBlock: medium]      → 中期蒸馏摘要
   human_blocks:
     [QuestionBlock]            → 用户问题 + 任务前缀
     [StepsBlock]               → 本轮 TAO 推理步骤
     [SuffixBlock]              → "Thought:" 引导后续输出

4. LLM.stream_generate_messages(messages)
      → 持续 yield ChunkEvent（流式 token）
      → 累积 raw_output

5. parse_llm_output(raw_output)
      → (thought, action, action_input)

6. executor.run({"action": action, "args": action_input})
      → observation（工具返回值）

7. processor.add(Step(thought, action, action_input, observation))
      → _trace.append(step)           （本轮推理链）
      → short.add(step)               → evicted: list[Step]
      → medium.absorb(evicted)
              → _pending.extend(evicted)
              → len(_pending) >= distill_trigger_steps → _distill()
                       → LLM 压缩 → _distillate；_pending 清空

8. yield StepEvent(...)
```

## finish 后台提交（post_process）

```
stream() 末尾，WebSocket 关闭后，后台线程执行：

processor.commit(question, answer)
      → medium.flush()                → 推送剩余 _pending
      → long.add(Q + Steps + Distillate + A)
         long.save()                  → memories.json + FAISS 索引
      → milestone.try_add(question, answer, trace)
            → ImportanceScorer.score()  （LLM 评分 0.0–1.0）
            → score >= threshold → MilestoneEntry → milestones.json

trace_store.write(question, answer, processor.trace)
      → .react/traces/{timestamp}_{slug}.json

persona.evolve(question, answer, processor.trace)
      → EvolutionEngine.run()
      │    → profile    : LLM 生成 ProfileDelta → traits/values/style 增量更新
      │    → skills     : LLM 生成 SkillDelta  → 技能增删改（每 N 轮触发）
      │    → reflect    : LLM 生成自省文本（每 M 轮触发，reflect_interval）
      → preference_updater.update(preference, question, answer)
               → LLM 生成快照 → 更新 mood / topic_interests / style_shifts
                  每 preference_update_every_n 轮持久化 preference.json

manager.add_turn(question, answer)
      → _history += [HumanMessage, AIMessage]

_maybe_consolidate()
      → turn_count % consolidation_k == 0 时
              → manager.recent_turns(k) → long.add(对话摘要) → long.save()

self._static_cache = manager.build_static(
    medium_term=processor.medium_distillate,
    extra_system_blocks=persona_blocks,
)    → 预热下轮静态 Prompt 片段
```

---

## 静态 Prompt 缓存（`StaticPromptParts`）

每次 `post_process()` 结束后**预热一次**，存为 `_static_cache`，下轮首步复用：

```python
@dataclass
class StaticPromptParts:
    system_without_lt: str       # base_system + persona + medium_term（不含长期记忆）
    history: list[BaseMessage]   # add_turn() 积累的历史对话
```

使用时仅需动态追加：
1. 将 `long_term` 内容拼接到 `system_without_lt`
2. 拼接 `question / short_term / suffix` 组成 Human 消息

避免每轮重新序列化 Persona / 中期记忆等"重"组件。

---

## 记忆四层设计

| 层 | 名称 | 存储 | 检索触发 | 注入位置 | 持久化 |
|---|---|---|---|---|---|
| L1 | 短期 | `ShortTermMemory`（内存 deque，token 窗口）| 每步自动 | Human 消息 StepsBlock | 否 |
| — | 中期蒸馏 | `MediumTermMemory`（内存，LLM 摘要）| 每问题自动 | System MemoryBlock | 否 |
| L2 | 里程碑 | `MilestoneMemory`（JSON + 关键词索引）| 仅首步（可选）| System + L3 拼接 | `milestones.json` |
| L3 | 长期 | `LongTermMemory`（FAISS + JSON）| 仅首步（可选）| System MemoryBlock | FAISS + JSON |

**短路策略**：L1→L3 层次递进，L1 步骤被 LLM 蒸馏后通过 `commit()` 写入 L3。

### L2 里程碑写入流程

```
commit() 时：
  ImportanceScorer.score(Q, A, trace)
    → LLM 评分 0.0–1.0
    → score >= threshold → MilestoneEntry(summary, detail, keywords, emotion, importance)
                            → MilestoneStore.add() → milestones.json

  溢出时（count > max_milestones）：
    按 importance 从低到高淘汰
    淘汰的条目自动迁移写入 L3，确保重要信息不丢失
```

### L3 五场景检索模式

L3 记忆每条带时间戳 `[YYYY-MM-DD HH:MM UTC]`，支持 5 种自动识别的检索场景：

| 模式 | 触发词示例 | 策略 |
|---|---|---|
| `LIGHT` | 一般问题 | 低精度快速检索 |
| `HEAVY` | "分析/研究/评估" | 扩大 top_k，拉高阈值 |
| `SUPPLEMENT` | 多轮追问 | 补充上下文 |
| `PROFILE` | 人格相关 | 融合人格查询偏置 |
| `TIMELINE` | "最近/上次/recently" | 时间序倒序取最近 N 条，不经 FAISS |

### MemoryProcessor 创建方式

```python
# TaoLoop 内部：绑定完整记忆层
processor = MemoryProcessor(cfg, llm, long_term=self._long_term, milestone=self._milestone)

# 轻量创建（仅短期 + 中期）
processor = MemoryProcessor(cfg, llm)
```

---

## Prompt 块系统

### 块层次

```
PromptBlock (ABC)
  render() -> str | None    # 返回 None 时该块跳过
│
├── SystemBlock(text)                      → ReAct 系统提示 + 工具描述
├── MemoryBlock(header, sep, content)      → 长期/中期记忆块
├── QuestionBlock(prefix, question)        → 用户问题
├── StepsBlock(format, steps)              → TAO 推理步骤序列
├── SuffixBlock(text)                      → "Thought:" 引导
│
└── Persona 子类（均继承 PromptBlock）：
    ├── ProfileBlock(profile)              → 人物画像
    ├── SkillsBlock(skills, top_k=5)       → 相关技能列表
    ├── ReflectionBlock(reflection)        → 自省文本（IROTE）
    └── PreferenceBlock(preference)        → 近期偏好（非 neutral 时注入）
```

### 消息构建路径

```
有 _static_cache（非首步）:
  build_messages_from_static(static, question, long_term, short_term)
    → system  = static.system_without_lt + [long_term 拼接]
    → history = static.history（上轮 add_turn 后的历史）
    → human   = question + short_term steps + suffix

无 _static_cache（首步或重置后）:
  build_messages(question, result, extra_system_blocks=persona_blocks)
    → 全量重新序列化所有块
```

### 历史管理

```python
manager.add_turn(q, a)       # _history.append([HumanMessage, AIMessage])
manager.recent_turns(k)      # list[(question, answer)]，用于 consolidate
manager.turn_count            # 当前轮数
manager.clear_history()      # TaoLoop.reset() 时调用
```

---

## Persona 系统

人格系统分**稳定层**（长期画像）和**动态层**（近期偏好），通过 `PersonaManager` 统一对外。

```
profile/store.py
  profile.json / skills.json / reflection.txt
         │
  PersonaProfile           SkillsLibrary
  （人物画像属性）          （技能知识图谱）
  reflection: str
  （自省 IROTE 文本）
         │
  EvolutionEngine.run()（每 N 轮触发）
    → LLM 生成 ProfileDelta  → profile 增量更新（每 evolve_interval 轮）
    → LLM 生成 SkillDelta    → skills 增删改（每 evolve_interval 轮）
    → LLM 生成 reflection    → 每 reflect_interval 轮更新

preference/（动态层，持久化到 preference.json）:
  PreferenceUpdater.update(Q, A)
    → LLM 生成快照 → 更新 mood / topic_interests / style_shifts
       结果影响 L3 检索偏置方向 + PreferenceBlock 注入 Prompt

PersonaManager.all_blocks()
  → [ProfileBlock, SkillsBlock?, ReflectionBlock?, PreferenceBlock?]
  → 注入 system prompt

PersonaManager.bias_query(question)
  → question + " " + topic_interests   → 影响 L3 检索向量方向
```

### 稳定层 vs 动态层

| 维度 | 稳定层（长期人格）| 动态层（近期偏好）|
|---|---|---|
| 内容 | profile / skills / reflection | mood / topic_interests / style_shifts |
| 更新频率 | LLM 每 N 轮触发一次 | LLM 每轮生成快照 |
| 持久化 | 各自 JSON 文件 | `preference.json` |
| L3 检索影响 | 无直接影响 | 偏置检索向量方向 |
| Prompt 注入 | 始终注入 | 非 neutral 时注入 |

详见 [persona/README.md](./persona/README.md)。

---

## Trace 存档

```
TraceStore.write(question, answer, steps)
  → .react/traces/{YYYYMMDD_HHMMSS}_{slug}.json
       {
         "id": "uuid",
         "timestamp": "...",
         "question": "...",
         "answer": "...",
         "steps": [{ "index", "thought", "action", "action_input", "observation" }]
       }
```

`processor.trace` 记录本轮所有步骤，在 `finish` 后由 `trace_store.write` 异步写入。

---

## ConvLoop 接口

```python
ConvLoop(tao: TaoLoop)

conv.stream(question)       # 代理 tao.stream()，向上层 yield TaoEvent
conv.post_process()         # 代理 tao.post_process()
conv.reset()                # tao.reset() → manager.clear_history() + 清空记忆
conv.restore(messages)      # 从历史 JSON 恢复：user/assistant → manager.add_turn()
conv.turn_count             # tao._manager.turn_count
```

---

## 类型速查表

| 类型名 | 定义位置 | 流转路径 |
|---|---|---|
| `Step` | `memory/memory.py` | tao → processor.add → short/medium → MemoryResult.short_term |
| `MemoryResult` | `memory/processor.py` | processor.recall → build_messages（含 milestone 文本）|
| `StaticPromptParts` | `prompt/manager.py` | post_process → _static_cache → build_messages_from_static |
| `list[BaseMessage]` | LangChain | build_messages → llm.stream_generate_messages |
| `TaoEvent` | `tao.py` | TaoLoop.stream → ConvLoop.stream → WebUI WebSocket |
| `MemoryEntry` | `memory/long_term/store.py` | LongTermStore.add → FAISS + memories.json |
| `MilestoneEntry` | `memory/milestone/entry.py` | ImportanceScorer.score → MilestoneStore.add → milestones.json |
| `ProfileDelta` | `persona/profile/evolver.py` | PersonaEvolver.evolve_profile → _apply_profile_delta |
| `SkillDelta` | `persona/profile/evolver.py` | PersonaEvolver.evolve_skills → _apply_skill_delta |
| `RecentPreference` | `persona/preference/recent.py` | PreferenceUpdater.update → preference.json |

---

## TaoConfig 字段树

```
TaoConfig
  ├── max_steps: int = 10
  ├── storage: StorageConfig               # 本地文件根目录（自动传播到各子模块）
  │     ├── root: str = ".react"
  │     └── 派生属性: memory_dir / milestones_dir / persona_dir / traces_dir
  ├── prompt: PromptConfig
  │     ├── lang: str = "en"              # "en" | "cn"
  │     ├── repair_enabled: bool = True
  │     └── retry_on_bad_parse: int = 2
  ├── memory: MemoryConfig
  │     ├── short_term:  ShortTermMemoryConfig
  │     │     ├── enabled: bool = True
  │     │     ├── max_turns: int = 10
  │     │     ├── max_tokens: int = 2048
  │     │     ├── distill_enabled: bool = True
  │     │     └── distill_trigger_steps: int = 4
  │     ├── medium_term: MediumTermMemoryConfig
  │     │     ├── enabled: bool = True
  │     │     └── max_distillate_tokens: int = 400
  │     ├── long_term:   LongTermMemoryConfig
  │     │     ├── enabled: bool = False
  │     │     ├── top_k: int = 5
  │     │     ├── model_name_or_path: str = "BAAI/bge-small-zh-v1.5"
  │     │     ├── consolidation_k: int = 0    # 0=禁用，N=每 N 轮 consolidate
  │     │     └── retrieve: RetrieveConfig
  │     │           ├── light_top_k / light_min_score
  │     │           ├── heavy_top_k / heavy_min_score
  │     │           ├── supplement_top_k / supplement_min_score
  │     │           ├── profile_top_k / profile_min_score
  │     │           └── timeline_top_k: int = 5
  │     └── milestone:   MilestoneConfig
  │           ├── enabled: bool = False
  │           ├── max_milestones: int = 50
  │           ├── importance_threshold: float = 0.6
  │           ├── max_keywords: int = 5
  │           ├── top_k_retrieve: int = 2
  │           └── prompt_header: str = "## 重要事件"
  ├── persona: PersonaConfig
  │     ├── enabled: bool = False
  │     ├── evolution_enabled: bool = False
  │     ├── evolve_interval: int = 1
  │     ├── skills_enabled: bool = True
  │     ├── max_skills_in_prompt: int = 5
  │     ├── reflection_enabled: bool = False
  │     ├── reflect_interval: int = 3
  │     ├── preference_enabled: bool = True
  │     ├── preference_window_days: int = 30
  │     └── preference_update_every_n: int = 3
  ├── trace: TraceConfig
  │     └── enabled: bool = True
  ├── knowledge: KnowledgeConfig | None = None
  └── repair_llm: LLMConfig | None = None
```

---

## 本地文件目录布局

```
.react/
├── history/              # WebUI 对话历史（/api/history 接口）
│   └── {uuid}.json
├── memory/               # L3 长期记忆（LongTermStore）
│   ├── memories.json
│   └── memory_index.faiss
├── milestones/           # L2 里程碑（MilestoneStore）
│   └── milestones.json
├── persona/              # 人格文件（ProfileStore / PreferenceStore）
│   ├── profile.json
│   ├── skills.json
│   ├── reflection.txt
│   └── preference.json
├── traces/               # 推理链存档（TraceStore）
│   └── {timestamp}_{slug}.json
└── knowledge_base/       # 知识库向量索引（Qdrant 本地文件）
    └── qdrant/
```

---

## 子模块文档

- [prompt/README.md](./prompt/README.md) — Prompt 块详解
- [memory/README.md](./memory/README.md) — 四层记忆系统
- [action/README.md](./action/README.md) — 工具动作空间
- [persona/README.md](./persona/README.md) — 人格演化引擎
