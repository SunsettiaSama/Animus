# agent/react 模块

ReAct（Reasoning + Acting）核心框架：**ConvLoop** + **TaoLoop**，会话上下文在 **`context/`**，向量长期与里程碑的逻辑实现在 **`agent/soul/memory`**（由 **`memory_recall`** 工具按需挂载）；Soul **`MemoryService`** 见 [agent/soul/README.md](../soul/README.md)。

---

## 目录结构

```
src/agent/react/
├── loop.py              # ConvLoop
├── tao.py               # TaoLoop — 推理循环与工具注入
├── parser.py            # 转发 prompt/parser 符号
├── factory.py           # build_conv_loop
├── context/             # MemoryProcessor + RecentHistoryMemory（会话上下文）
│   ├── processor.py
│   ├── memory.py        # Step
│   └── medium_term/memory.py
├── prompt/              # PromptManager / parser / repair / template
├── action/              # Tool / MCP / Skill — 见 action/README.md
├── trace/store.py       # TraceStore
└── （人格 / 生命：`agent/soul/persona`、`agent/soul/life`）
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
   │     ├─ processor.recall()  → MemoryResult（short_term + medium_term）
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
| `_long_term` | `LongTermMemory \| None` | soul 包向量层；**默认不写入 Prompt**，供 `memory_recall` / consolidation |
| `_milestone` | `MilestoneMemory \| None` | soul 包里程碑；同上 |
| `_medium_term` | `RecentHistoryMemory \| None` | 中期 JSONL（`context/medium_term`）|
| `_soul_memory` | `MemoryService \| None` | `cfg.db` 全启用时构造；ingest_turn + recall 工具后端 |
| `_persona` | `PersonaManager \| None` | 人格块（无 `bias_query` 钩子）|
| `_life` | `LifeManager \| None` | 生活状态管理（心跳日志 + 日度综合）|
| `_scheduler_engine` | `SchedulerEngine \| None` | 时钟触发任务引擎（`TaoConfig.scheduler` 非空时启用）|
| `_delegate_skill` | `DelegateTaskSkill \| None` | 子 Agent 同步委派（`TaoConfig.agent` 非空时注入）|
| `_flow_orchestrator` | `FlowOrchestrator \| None` | Flow DAG 编排（`TaoConfig.flow` 非空时启用）|
| `_static_cache` | `StaticPromptParts \| None` | `post_process` 预热的静态 Prompt 片段 |
| （每轮构造） | `MemoryProcessor` | 仅存于 `stream()` 局部变量；负责 trace + medium_term |

---

## 单步推理流程（stream 内循环）

```
1. processor.recall()
      → short_term : list[Step]
      → medium_term : str（RecentHistoryMemory；首轮缓存后在后续 step 复用）

2. Prompt 组装
     · 首轮或无缓存：PromptManager.build_messages(question, result, persona_blocks)
         → system：base + persona + medium_term MemoryBlock
         → human：question + StepsBlock(short_term) + suffix
     · 后续轮：build_messages_from_static(static_cache, question, medium_term, short_term)
         → docstring：长期记忆仅靠 memory_recall 工具触发

3. LLM 流式生成 → parse → executor.run(tool) → processor.add(Step)
```

长期 / 里程碑 / Soul：**不**在上述 Prompt 路径中拼接；Agent 调用 **`memory_recall`** 将观测写入对话。

---

## finish 后台提交（post_process）

```
processor.commit(question, answer)        → RecentHistoryMemory.append（JSONL）

MemoryService.ingest_turn(...)（线程）   → 若 cfg.db 启用 Soul

_maybe_consolidate()                     → 可选：窗口整合写入 legacy LongTermMemory

timeline.append("conversation", {...})

trace_store.write(...)

persona.evolve(..., processor.trace, medium_term_chunk)

manager.add_turn + build_static → _static_cache
```

---

## 记忆相关文档

| 文档 | 说明 |
|---|---|
| [context/README.md](./context/README.md) | `MemoryProcessor`、`RecentHistoryMemory` |
| [../soul/memory/README.md](../soul/memory/README.md) | `MemoryService`、`LongTermMemory`、`MilestoneMemory`、`memory_recall` 后端 |

旧的 **`agent/react/memory/`** 源码树已拆除；向量与里程碑逻辑在 **`agent/soul/memory`**。

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

### 消息构建路径（与 `prompt/manager.py` 一致）

```
有 _static_cache（非首轮拼装）:
  build_messages_from_static(static, question, medium_term, short_term)
    → system = static.system + medium_term 块
    → human  = question + StepsBlock(short_term) + suffix

无 _static_cache（首轮或重置后）:
  build_messages(question, MemoryResult, extra_system_blocks=persona_blocks)
    → system = base + persona 块 + medium_term 块
    → human  = question + StepsBlock(short_term) + suffix
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

preference/  →  preference.json（动态层）:
  PreferenceUpdater.update(Q, A)
    → LLM 生成快照 → PreferenceBlock 注入

emotional/  →  emotional_state.json（叙事情感层）:
  EmotionalStateEvolver.update(Q, A)
    → LLM 追加 EmotionalAnchor（锚点 ≥ _MAX_ANCHORS 时压缩为 texture）
       结果注入 EmotionalStateBlock → 系统提示情绪质地
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
  ├── knowledge: KnowledgeConfig | None = None   # 遗留字段：运行时包 `knowledge` 已移除，勿启用
  ├── repair_llm: LLMConfig | None = None
  ├── scheduler: SchedulerConfig | None = None   # runtime.scheduler；时钟触发任务（见 docs/runtime）
  ├── agent: SubAgentConfig | None = None         # 子 Agent 委派（注入 DelegateTaskSkill）
  │     ├── llm_cfg_path: str
  │     ├── max_concurrent: int = 4
  │     └── profiles: dict[str, SubAgentProfile]
  ├── flow: FlowConfig | None = None              # Flow DAG / cluster 编排
  └── db: DBConfig | None = None                  # Soul：Redis/MySQL（可选）
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
│   └── qdrant/           # L3 Qdrant 本地集合
├── milestones/           # 里程碑记忆
│   └── milestones.json
├── persona/              # 人格文件
│   ├── profile.json
│   ├── skills.json
│   ├── reflection.txt
│   ├── preference.json
│   └── emotional_state.json
├── traces/               # 推理链存档
│   └── {timestamp}_{slug}.json
├── scheduler/            # 调度持久化目录（TaskStore；心跳清单 HEARTBEAT.md；详见 docs/runtime）
│   ├── tasks.json
│   ├── heartbeat_log.jsonl
│   └── results/
├── timeline/             # 会话级时间线事件
│   └── {YYYY-MM-DD}.jsonl
├── life/                 # LifeManager（账本 / 叙事 / 体验 / 画像）
│   ├── tao_dialogue.jsonl
│   ├── narrative_events.jsonl
│   ├── experience_hot.jsonl
│   ├── life_profile.json
│   ├── story_outline.json
│   └── story_arc.json
└── workspace/            # 沙箱工作区文件
```

---

## 子模块文档

- [action/README.md](./action/README.md) — 工具动作空间（Tool / MCP / Skill）
- [context/README.md](./context/README.md) — 会话上下文（MemoryProcessor）
- [prompt/README.md](./prompt/README.md) — Prompt 块详解
- [persona/README.md](./persona/README.md) — 人格文档入口（实现见 [../soul/persona/README.md](../soul/persona/README.md)）
- [../soul/life/README.md](../soul/life/README.md) — LifeManager / 生活状态