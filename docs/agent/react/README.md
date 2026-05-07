# agent/react 模块

ReAct（Reasoning + Acting）核心框架，实现两层循环结构、四层记忆系统、块驱动 Prompt 组装、人格演化引擎和推理链存档。

---

## 目录结构

```
src/agent/react/
├── loop.py              # ConvLoop — 外层多轮对话循环
├── tao.py               # TaoLoop  — 内层 TAO 推理循环 + 事件流
├── parser.py            # ReActOutputParser / LLM 输出解析
├── factory.py           # TaoLoop 工厂函数
│
├── memory/              # 四层记忆系统（L1 短期 / L2 中期 / 里程碑 / L3 长期）
│   ├── memory.py        # Step + Memory 基础数据结构
│   ├── processor.py     # MemoryProcessor：统一读写接口
│   ├── short_term/      # L1 短期（Token 滑动窗口 + 蒸馏摘要）
│   ├── medium_term/     # L2 中期（跨 session JSONL Q&A 历史 + 滚动整合）
│   ├── long_term/       # L3 长期（BGE Embedding + FAISS + RAG）
│   │   ├── memory.py
│   │   ├── store.py     # LongTermStore（向量 + 时间戳 + 持久化）
│   │   ├── init/        # make_memory 工厂函数
│   │   └── retrieve/    # Retriever + 四场景检索模式
│   └── milestone/       # 里程碑记忆（重要事件，关键词检索）
│       ├── entry.py     # MilestoneEntry 数据类
│       ├── store.py     # MilestoneStore（JSON 持久化）
│       ├── retriever.py # MilestoneRetriever（关键词匹配 + jieba 可选）
│       ├── scorer.py    # ImportanceScorer（LLM 评分 0.0–1.0）
│       ├── memory.py    # MilestoneMemory 门面
│       └── init.py      # make_milestone 工厂函数
│
├── prompt/              # Prompt 块驱动组装系统
│   ├── block.py         # PromptBlock 基类 + 内置块
│   ├── manager.py       # PromptManager：Prompt 构建 + 静态缓存
│   ├── builder.py       # PromptBuilder：纯文本组装（辅助路径）
│   ├── parser.py        # ReActOutputParser + ParseQuality 枚举
│   ├── repair.py        # Prompt 修复（输出格式错误时重试）
│   └── template.py      # ReActTemplate 语言模板（CN / EN）
│
├── persona/             # 人格演化系统（知识-技能-反省三层 + 近期偏好）
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
├── action/              # 动作空间（Tool / MCP / Skill）
│   └── ...              # 见 action/README.md
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
   │     ├─ LLM.stream_generate_messages()    → raw_output（流式 chunk）
   │     ├─ parse_llm_output()               → (thought, action, action_input)
   │     │
   │     ├─ [finish] → yield FinishEvent → 客户端立即收到答案
   │     └─ [tool]   → executor.run() → processor.add(Step)
   │
   FinishEvent.answer 发送完毕，WebSocket 关闭
   │
   └─ post_process()（后台线程，用户无感知）
         commit + trace + persona + add_turn + build_static
```

---

## TaoLoop 核心属性

| 属性 | 类型 | 说明 |
|---|---|---|
| `_manager` | `PromptManager` | 负责 Prompt 构建与历史管理 |
| `_long_term` | `LongTermMemory \| None` | L3 FAISS 向量存储与检索 |
| `_milestone` | `MilestoneMemory \| None` | 里程碑事件检索与评分 |
| `_medium_term` | `RecentHistoryMemory \| None` | L2 中期跨 session JSONL 历史 |
| `_trace_store` | `TraceStore \| None` | 写入推理链到 `.react/traces/` |
| `_persona` | `PersonaManager \| None` | 人格注入 + 演化 + 检索偏置 |
| `_scheduler_engine` | `SchedulerEngine \| None` | 时钟触发任务引擎（`TaoConfig.scheduler` 非空时启用）|
| `_delegate_skill` | `DelegateTaskSkill \| None` | 子 Agent 同步委派（`TaoConfig.agent` 非空时注入）|
| `_plan_orchestrator` | `PlanOrchestrator \| None` | Plan 多智能体编排（`TaoConfig.plan` 非空时启用）|
| `_static_cache` | `StaticPromptParts \| None` | `post_process` 预热的静态 Prompt 片段 |
| `processor` | `MemoryProcessor` | 统一读写 short_term + medium_term + long_term + milestone |

---

## 单步推理流程（stream 内循环）

```
1. 偏置查询向量（L3 检索方向）
   recall_query = persona.bias_query(question)   ← 融合近期话题偏好

2. processor.recall(recall_query, include_long_term=(i==0))
      → short_term          : list[Step]  （当前 session 推理步骤）
      → short_term_distillate: str        （被驱逐步骤的 LLM 摘要）
      → medium_term         : str         （跨 session Q&A 历史，仅首步检索）
      → long_term           : str         （仅首步检索 L3 FAISS 向量结果）
      → milestone           : str         （仅首步检索里程碑关键词结果）

3. Prompt 构建（system blocks）
   [SystemBlock]              → ReAct 系统提示 + 工具描述
   [ProfileBlock]             → 人物画像（persona 启用时）
   [SkillsBlock]              → 技能列表（skills_enabled 时）
   [ReflectionBlock]          → 自省文本（reflection_enabled 且非空时）
   [PreferenceBlock]          → 近期偏好（preference_enabled 且非 neutral 时）
   [MemoryBlock: medium_term] → L2 跨 session 历史
   [MemoryBlock: milestone]   → 里程碑记忆
   [MemoryBlock: long_term]   → L3 向量结果
   human:
   [QuestionBlock]            → 用户问题 + 任务前缀
   [MemoryBlock: distillate]  → L1 蒸馏摘要
   [StepsBlock]               → 本轮 TAO 推理步骤
   [SuffixBlock]              → "Thought:" 引导后续输出

4. LLM.stream_generate_messages(messages)
      → 持续 yield ChunkEvent（流式 token）

5. parse_llm_output(raw_output)
      → (thought, action, action_input)

6. executor.run({"action": action, "args": action_input})
      → observation（工具返回值）

7. processor.add(Step(...))
```

## finish 后台提交（post_process）

```
processor.commit(question, answer)
      → short_term.flush()
      → medium_term.append(Q, A)     → 写入 JSONL，异步整合
      → long_term.add(Q+Steps+A).save()  → FAISS + memories.json
      → milestone.try_add(Q, A, trace)
            → ImportanceScorer → score >= threshold → milestones.json

trace_store.write(question, answer, processor.trace)
      → .react/traces/{timestamp}_{slug}.json

persona.evolve(question, answer, processor.trace)
      → EvolutionEngine（profile / skills / reflect / preference）

manager.add_turn(question, answer)
      → _history += [HumanMessage, AIMessage]

self._static_cache = manager.build_static(...)   ← 预热下轮
```

---

## 记忆四层设计

| 层 | 名称 | 实现类 | 检索触发 | 持久化 |
|---|---|---|---|---|
| L1 | 短期 | `ShortTermMemory`（内存 deque）| 每步自动 | ❌ |
| L1 蒸馏 | 短期蒸馏 | `ShortTermMemory._distillate`（内存）| 随 L1 溢出触发 | ❌ |
| L2 | 中期 | `RecentHistoryMemory`（JSONL）| 仅首步，跨 session | ✅ `.react/memory/medium_term.jsonl` |
| 里程碑 | 重要事件 | `MilestoneMemory`（JSON + 关键词索引）| 仅首步（可选）| ✅ `milestones.json` |
| L3 | 长期 | `LongTermMemory`（FAISS + JSON）| 仅首步（可选）| ✅ FAISS + JSON |

**L2 中期说明**：`RecentHistoryMemory` 以 JSONL 形式持久化跨 session 的近期 Q&A 对，按 `window_days` 时间窗口加载。超出 `max_entries` 时触发 LLM 滚动整合（条目合并为摘要条目）。

**里程碑溢出策略**：条目数超过 `max_milestones`（默认 50）时，按 importance 从低到高淘汰，被淘汰条目自动迁移写入 L3。

---

## Prompt 块系统

```
PromptBlock (ABC)
  render() -> str | None    # 返回 None 时该块跳过
│
├── SystemBlock(text)
├── MemoryBlock(title, desc, separator, content)
├── QuestionBlock(prefix, question)
├── StepsBlock(format, steps)
├── SuffixBlock(text)
│
└── Persona 子类：
    ├── ProfileBlock(profile)
    ├── SkillsBlock(skills, top_k=5)
    ├── ReflectionBlock(reflection)
    └── PreferenceBlock(preference)
```

### 消息构建路径

```
有 _static_cache（非首步）:
  build_messages_from_static(static, question, long_term, medium_term, milestone, short_term)
    → system  = static.system_without_lt + 记忆拼接
    → history = static.history
    → human   = question + distillate + short_term steps + suffix

无 _static_cache（首步或重置后）:
  build_messages(question, result, extra_system_blocks=persona_blocks)
    → 全量重新序列化所有块
```

---

## Persona 系统

```
profile/store.py  →  profile.json / skills.json / reflection.txt
       │
  PersonaProfile           SkillsLibrary
  （人物画像属性）          （技能知识图谱）
  reflection: str
  （自省 IROTE 文本）
       │
  EvolutionEngine.run()（每 N 轮触发）
    → LLM 生成 ProfileDelta  → profile 增量更新
    → LLM 生成 SkillDelta    → skills 增删改
    → LLM 生成 reflection

preference/  →  preference.json（动态层，持久化）:
  PreferenceUpdater.update(Q, A)
    → LLM 生成快照 → 更新 mood / topic_interests / style_shifts
       结果影响 L3 检索偏置方向 + PreferenceBlock 注入 Prompt
```

---

## ConvLoop 接口

```python
from agent.react.loop import ConvLoop

conv = ConvLoop(tao)

conv.stream(question)       # 代理 tao.stream()，向上层 yield TaoEvent
conv.post_process()         # 代理 tao.post_process()
conv.reset()                # tao.reset() → manager.clear_history() + 清空记忆
conv.restore(messages)      # 从历史 JSON 恢复：user/assistant → manager.add_turn()
conv.turn_count             # tao._manager.turn_count
```

---

## TaoConfig 字段树

```
TaoConfig
  ├── max_steps: int = 10
  ├── storage: StorageConfig               # 本地文件根目录（自动传播到各子模块）
  │     ├── root: str = ".react"
  │     └── 派生属性: memory_dir / milestones_dir / persona_dir / traces_dir / scheduler_dir
  ├── prompt: PromptConfig
  │     ├── lang: str = "en"              # "en" | "cn"
  │     ├── repair_enabled: bool = True
  │     └── retry_on_bad_parse: int = 2
  ├── memory: MemoryConfig
  │     ├── short_term:  ShortTermMemoryConfig
  │     ├── medium_term: MediumTermMemoryConfig
  │     ├── long_term:   LongTermMemoryConfig
  │     └── milestone:   MilestoneConfig
  ├── persona: PersonaConfig
  │     ├── enabled: bool = False
  │     ├── evolution_enabled: bool = False
  │     ├── evolve_interval: int = 1
  │     ├── skills_enabled: bool = True
  │     ├── max_skills_in_prompt: int = 5
  │     ├── reflection_enabled: bool = False
  │     ├── reflect_interval: int = 3
  │     ├── preference_enabled: bool = True
  │     └── preference_window_days: int = 30
  ├── trace: TraceConfig
  │     └── enabled: bool = True
  ├── knowledge: KnowledgeConfig | None = None
  ├── repair_llm: LLMConfig | None = None
  ├── scheduler: SchedulerConfig | None = None   # 时钟触发的自动化任务
  ├── agent: SubAgentConfig | None = None         # 子 Agent 委派（注入 DelegateTaskSkill）
  │     ├── llm_cfg_path: str
  │     ├── max_concurrent: int = 4
  │     └── profiles: dict[str, SubAgentProfile]
  └── plan: PlanConfig | None = None              # Plan-and-Execute 多智能体编排
```

---

## 本地文件目录布局

```
.react/
├── history/              # WebUI 对话历史
│   └── {uuid}.json
├── memory/               # L2 中期 + L3 长期记忆
│   ├── medium_term.jsonl # L2 中期 Q&A 历史（JSONL，跨 session）
│   ├── memories.json     # L3 长期记忆条目
│   └── memory_index.faiss
├── milestones/           # 里程碑记忆
│   └── milestones.json
├── persona/              # 人格文件
│   ├── profile.json
│   ├── skills.json
│   ├── reflection.txt
│   └── preference.json
├── traces/               # 推理链存档
│   └── {timestamp}_{slug}.json
└── scheduler/            # 调度任务持久化
    ├── tasks.json
    └── results/
```

---

## 子模块文档

- [action/README.md](./action/README.md) — 工具动作空间（Tool / MCP / Skill）
- [memory/README.md](./memory/README.md) — 四层记忆系统
- [prompt/README.md](./prompt/README.md) — Prompt 块详解
- [persona/README.md](./persona/README.md) — 人格演化引擎
