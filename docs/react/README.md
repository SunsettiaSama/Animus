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
├── memory/              # 三级记忆系统
│   ├── memory.py        # Step + Memory 基础数据结构
│   ├── processor.py     # MemoryProcessor — 三级记忆统一入口
│   ├── short_term/      # 短期：Token 滑动窗口
│   ├── medium_term/     # 中期：蒸馏（LLM 提炼被驱逐步骤）
│   └── long_term/       # 长期：BGE Embedding + FAISS + RAG
│       ├── memory.py
│       ├── store.py     # LongTermStore（向量库 + 持久化）
│       ├── init/        # make_memory 工厂函数
│       └── retrieve/    # Retriever + 四场景自动检索
│
├── prompt/              # Prompt 编排（块驱动）
│   ├── block.py         # PromptBlock 基类 + 5 个内置块
│   ├── manager.py       # PromptManager — 消息式组装 + 静态缓存
│   ├── builder.py       # PromptBuilder — 纯文本组装（辅助）
│   └── template.py      # ReActTemplate 中英预设
│
├── persona/             # 人格演化模块
│   ├── profile.py       # PersonaProfile — 人物画像
│   ├── chronicle.py     # PersonaChronicle — 事件演化日志
│   ├── store.py         # PersonaStore — 持久化
│   ├── manager.py       # PersonaManager — 统一管理 + evolve
│   └── block.py         # PersonaBlock（继承 PromptBlock）
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
| `_long_term` | `LongTermMemory \| None` | TaoLoop 级（**单例**）| FAISS 向量库，跨问题共享 |
| `_trace_store` | `TraceStore \| None` | TaoLoop 级 | 推理链写入 `.react/traces/` |
| `_persona` | `PersonaManager \| None` | TaoLoop 级 | 人物画像 + 事件演化 |
| `_static_cache` | `StaticPromptParts \| None` | TaoLoop 级 | 上轮 post_process 预构建的静态 Prompt 部件 |
| `_pending_finish` | `_PendingFinish \| None` | 跨方法传递 | stream() 存入，post_process() 消费 |
| `processor` | `MemoryProcessor` | **每问题新建** | 三级记忆，接收注入的 long_term |

---

## 单步执行完整流程

### 非 finish 步骤

```
① processor.recall(question, include_long_term=(i==0))
      ├─ short_term  → list[Step]  （短期窗口内的完整步骤）
      ├─ medium_term → str         （被驱逐步骤的蒸馏结果）
      └─ long_term   → str         （仅 i==0 时执行 FAISS 检索，后续步骤复用缓存）

② Prompt 组装（两条路径）
      有 _static_cache → manager.build_messages_from_static(cache, question, long_term, short_term)
                              ↳ system = cache.system_without_lt + long_term 块（注入槽位）
                              ↳ history = cache.history（快照）
      无 _static_cache → manager.build_messages(question, result, extra_system_blocks=persona_blocks)
                              ↳ 完整渲染 system/persona/medium_term

      system_blocks（完整路径）:
        [SystemBlock]            ← ReAct 指令 + 工具列表（必有）
        [PersonaBlock]           ← 人物画像 + 近期经历（可选，persona 启用时）
        [MemoryBlock: long_term] ← 长期检索（有内容时）
        [MemoryBlock: medium]    ← 蒸馏（有内容时）
      human_blocks:
        [QuestionBlock]          ← 问题前缀 + 问题（必有）
        [StepsBlock]             ← 当前轮 TAO 轨迹（有步骤时）
        [SuffixBlock]            ← "Thought:"（必有）
      → list[BaseMessage]

③ llm.stream_generate_messages(messages)
      → 流式产出 chunk，yield ChunkEvent
      → 拼成 raw_output

④ parse_llm_output(raw_output)
      → (thought, action, action_input)

⑤ executor.run({"action": action, "args": action_input})
      → observation（字符串）

⑥ processor.add(Step(thought, action, action_input, observation))
      ├─ _trace.append(step)           ← 完整链路，永不驱逐
      ├─ short.add(step)               → evicted: list[Step]
      └─ medium.absorb(evicted)
              ├─ _pending.extend(evicted)
              └─ len(_pending) >= distill_trigger_steps → _distill()
                       └─ LLM → 更新 _distillate，_pending 清空

⑦ yield StepEvent(...)
```

### finish 步骤（新的两阶段设计）

```
──── 阶段一：stream() 内（同步，用户等待这部分）────

self._pending_finish = _PendingFinish(question, answer, processor, persona_blocks)
yield FinishEvent(answer=answer)   ← 客户端立即收到答案，WebSocket 关闭

──── 阶段二：post_process()（后台线程，用户无感知）────

processor.commit(question, answer)
      ├─ medium.flush()                ← 强制蒸馏剩余 _pending
      └─ long.add(Q + Steps + Distillate + A)
         long.save()                   ← 写 memories.json + FAISS 索引

trace_store.write(question, answer, processor.trace)
      └─ 写 .react/traces/{timestamp}_{slug}.json

persona.evolve(question, answer, processor.trace)
      └─ _build_narrative() → chronicle.append() → save_chronicle()

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

| 层级 | 类 | 存储 | 生命周期 | prompt 注入位置 |
|---|---|---|---|---|
| 短期 | `ShortTermMemory` | 内存 deque（token 滑动窗口）| 本问题内 | Human 消息的 StepsBlock |
| 中期 | `MediumTermMemory` | 内存字符串（LLM 蒸馏）| 本问题内，commit 时入长期 | System 消息的 MemoryBlock |
| 长期 | `LongTermMemory` | FAISS + JSON（磁盘）| 永久（TaoLoop 单例）| System 消息的 MemoryBlock |

### 长期检索优化：单次查询复用

在同一问题的多步 ReAct 循环中，长期记忆只在第 0 步执行向量检索，之后步骤复用结果：

```python
result = processor.recall(question, include_long_term=(i == 0))
if i == 0:
    _cached_lt = result.long_term
# i > 0 时 result.long_term == ""，使用 _cached_lt
```

### MemoryProcessor 注入模式

```python
# TaoLoop 注入长期记忆单例（推荐）
processor = MemoryProcessor(cfg, llm, long_term=self._long_term)

# 独立使用时自行创建（向后兼容）
processor = MemoryProcessor(cfg, llm)  # long_term 由 cfg 决定是否创建
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
└── PersonaBlock(profile, chronicle)  → 人物画像 + 近期经历（persona/block.py）
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

```
PersonaStore（磁盘）
  .react/persona/
    ├── profile.json    ← PersonaProfile（永久，手动编辑或程序更新）
    └── chronicle.json  ← PersonaChronicle（累积，每轮 finish 追加）

PersonaManager
  ├── profile  → PersonaProfile（人物画像）
  ├── chronicle → PersonaChronicle（事件演化日志）
  └── evolve(q, a, steps)
        └─ _build_narrative() → 小说风格叙事
           chronicle.append() → save_chronicle()

PersonaBlock.render()
  ├─ profile.render()           ← 【人物画像】姓名、背景、性格、价值观、风格
  └─ [如有] chronicle.render(recent=N) ← 最近 N 条经历
```

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
| `MemoryResult` | `memory/processor.py` | processor.recall → build_messages |
| `StaticPromptParts` | `prompt/manager.py` | post_process → _static_cache → build_messages_from_static |
| `list[BaseMessage]` | LangChain | build_messages → llm.stream_generate_messages |
| `TaoEvent` | `tao.py` | TaoLoop.stream → ConvLoop.stream → webui/调用方 |
| `MemoryEntry` | `memory/long_term/store.py` | LongTermStore.add → FAISS + memories.json |
| `ChronicleEntry` | `persona/chronicle.py` | PersonaChronicle.append → chronicle.json |

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
  │     └── long_term:   LongTermMemoryConfig
  │           ├── enabled: bool = False
  │           ├── load_from_disk: bool = False
  │           ├── memory_dir: str = "long_term_memory"
  │           ├── top_k: int = 5
  │           ├── model_name_or_path: str = "BAAI/bge-small-zh-v1.5"
  │           ├── consolidation_k: int = 0   ← 0=禁用；N=每N轮合并一次
  │           └── retrieve: RetrieveConfig
  ├── prompt: PromptConfig
  │     └── lang: str = "en"   # "en" | "cn"
  ├── trace: TraceConfig
  │     ├── enabled: bool = True
  │     └── trace_dir: str = ".react/traces"
  └── persona: PersonaConfig
        ├── enabled: bool = False
        ├── persona_dir: str = ".react/persona"
        ├── max_chronicle_entries: int = 100
        └── chronicle_recent_in_prompt: int = 5
```

---

## 本地存储布局

```
.react/
├── {uuid}.json           ← webui 对话历史（/api/history 管理）
├── traces/               ← 推理链存档（TraceStore）
│   └── {timestamp}_{slug}.json
└── persona/              ← 人格数据（PersonaStore）
    ├── profile.json
    └── chronicle.json

long_term_memory/         ← 长期记忆（LongTermStore，路径可配）
├── memories.json
└── memory_index.faiss
```

---

## 子模块文档

- [prompt/README.md](./prompt/README.md) — Prompt 块架构详解
- [memory/README.md](./memory/README.md) — 三级记忆系统
- [action/README.md](./action/README.md) — 动作注册与执行
