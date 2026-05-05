# ReAct 项目总览

基于 ReAct（Reasoning + Acting）范式的智能体框架，支持本地 Transformer 推理与 OpenAI 兼容 API，集成三层记忆系统、人格演化引擎与可扩展动作空间。

---

## 项目结构

```
src/
├── config/                  # 所有模块的配置 dataclass
│   ├── llm_core/            # LLM 核心配置
│   ├── knowledge/           # 知识库配置（MySQL / Redis / Qdrant / 嵌入）
│   ├── tts/                 # TTS / STT 配置
│   └── react/               # ReAct 各子模块配置
│       ├── memory/          # 记忆模块配置（short/medium/long/milestone）
│       └── persona_config   # 人格配置（含近期偏好字段）
├── llm_core/                # LLM 抽象层（本地 + OpenAI API）
├── knowledge/               # 知识库（MySQL + Redis + Qdrant）
│   ├── store.py             # MySQL CRUD（documents / content_blobs / doc_chunks）
│   ├── vector_store.py      # Qdrant 向量索引
│   ├── cache.py             # Redis 缓存（查询 / chunk / 版本）
│   ├── embedder.py          # BGE 嵌入模型（懒加载，线程安全）
│   ├── ingestion.py         # 写入：分块 → 嵌入 → MySQL + Qdrant
│   ├── retriever.py         # 检索：keyword / semantic / hybrid
│   └── schema.sql           # MySQL 建表脚本
├── tts/                     # 语音合成 / 识别
│   ├── tts/                 # TTSEngine + Edge / OpenAI / Kokoro providers
│   └── stt/                 # STTEngine + OpenAI / faster-whisper providers
├── scheduler/               # 时钟触发的 Agent 自动化任务
│   ├── config.py            # SchedulerConfig + 执行 profile 预设
│   ├── task.py              # ScheduledTask + Trigger + TaskStatus
│   ├── store.py             # TaskStore（tasks.json 持久化）
│   ├── engine.py            # SchedulerEngine（async 轮询 + 任务分发）
│   └── runner.py            # TaskRunner（线程内同步运行 TaoLoop）
├── crew/                    # 主 Agent 按需委派的子 Agent 编排层（TaoLoop 当前使用）
│   ├── config.py            # CrewConfig + CrewProfile（含工具集 + 角色描述 + recursive + return_log）
│   ├── result.py            # CrewResult dataclass
│   ├── runner.py            # CrewRunner（线程内同步运行子 TaoLoop）
│   └── manager.py           # CrewManager（delegate / spawn / spawn_all / await_*）
├── subagent/                # 向后兼容 shim（重导出 delegate/ 的类，仅保留兼容性）
├── delegate/                # 子 Agent 编排层（已从 subagent/ 重命名，职责更清晰）
│   ├── config.py            # DelegateConfig + DelegateProfile（SubAgentConfig/Profile 为别名）
│   ├── result.py            # DelegateResult dataclass（SubAgentResult 为别名）
│   ├── runner.py            # DelegateRunner（SubAgentRunner 为别名）
│   └── manager.py           # DelegateManager（SubAgentManager 为别名）
├── agent/                   # 统一 Agent 接口层
│   └── base.py              # AgentBase 抽象基类 + AgentResult dataclass
├── plan/                    # Plan-and-Execute 多智能体编排层
│   ├── config.py            # PlannerConfig / ReplannerConfig / OrchestratorConfig / LogConfig
│   ├── document.py          # PlanDocument IR（PlanTask/PlanModule/PlanMetadata）+ PlanParser + PlanValidator + CycleDetector
│   ├── event.py             # PlanEvent 联合类型（任务/重规划/快照等 10 种事件）
│   ├── patch.py             # HumanPatch + PlanDiff（计算 / 应用人类编辑差异）
│   ├── channel.py           # HumanEditChannel（shadow copy 文件监视 + patch 队列）
│   ├── snapshot.py          # SnapshotStore（计划版本快照 + 回滚）
│   ├── log.py               # PlanLogger（JSONL 结构化日志 + read_async）
│   ├── executor.py          # ExecutorAgent（单个 PlanTask → CrewRunner 执行）
│   ├── planner.py           # PlannerAgent（自动规划）+ ConvPlanner（对话式规划）
│   ├── replanner.py         # ReplannerAgent（增量上下文 + 修补决策）
│   ├── orchestrator.py      # PlanOrchestrator（异步 DAG 调度 + 资源守卫 + 人类编辑集成）
│   └── result.py            # PlanResult dataclass
├── react/                   # ReAct 核心框架
│   ├── action/              # 动作空间（工具 + MCP + Skill）
│   ├── memory/              # 三层记忆系统
│   │   ├── short_term/      # L1 短期（Token 滑动窗口）
│   │   ├── medium_term/     # 中期蒸馏（LLM 提炼）
│   │   ├── long_term/       # L3 长期（BGE + FAISS，含时序召回）
│   │   └── milestone/       # L2 里程碑（重要事件，关键词检索）
│   ├── prompt/              # 块驱动 Prompt 组装 + 静态缓存
│   ├── persona/             # 人格演化（稳定层 + 动态层）
│   │   ├── profile/         # 长期人格：画像 + 技能库 + 自省
│   │   └── preference/      # 近期偏好：情绪 / 话题兴趣 / 风格偏移（k 天滑动窗口）
│   ├── trace/               # 推理链存档
│   ├── loop.py              # ConvLoop — 外层多轮对话循环
│   ├── tao.py               # TaoLoop  — 内层 TAO 推理循环
│   └── parser.py            # LLM 输出解析
├── embedding/               # BGE 嵌入模型（FAISS 索引构建辅助）
├── storage/                 # 本地文件存储根目录配置（StorageConfig）
├── webui/                   # Web 前端（FastAPI + 单页 HTML）
└── test/                    # 测试套件（plan/ + delegate/ + react/ + tools/ + memory/ + ...）
```

---

## 已完成模块

| 模块 | 状态 | 说明 |
|---|---|---|
| `llm_core` | ✅ | 本地推理 + OpenAI API 双后端，流式输出 |
| `react/action` | ✅ | 工具注册、Pydantic 参数校验、执行调度（Tool / MCP / Skill）|
| `react/memory/short_term` | ✅ | Token 级滑动窗口 L1 短期记忆 |
| `react/memory/medium_term` | ✅ | LLM 蒸馏中期记忆，被驱逐步骤压缩摘要 |
| `react/memory/long_term` | ✅ | L3 BGE + FAISS，时间戳感知，五场景自动检索（含 TIMELINE）|
| `react/memory/milestone` | ✅ | L2 里程碑，LLM 重要性评分，关键词精确匹配（jieba 可选），detail 注入，溢出迁移 L3 |
| `react/prompt` | ✅ | 块驱动组装 + `StaticPromptParts` 静态缓存预热 |
| `react/persona/profile` | ✅ | 人物画像 + 技能库 + 自省（IROTE），LLM 演化引擎 |
| `react/persona/preference` | ✅ | 短期偏好动态层（mood / 话题兴趣 / 风格偏移），影响 L3 检索偏置 |
| `react/trace` | ✅ | 推理链存档（`.react/traces/`）|
| `react/loop` | ✅ | ConvLoop + TaoLoop 两层循环，异步后台提交，Prompt 预热 |
| `knowledge` | ✅ | MySQL 文档存储 + Qdrant 向量索引 + Redis 缓存，keyword / semantic / hybrid 三种检索 |
| `tts` | ✅ | TTS（Edge / OpenAI / Kokoro）+ STT（OpenAI / faster-whisper）语音模块 |
| `scheduler` | ✅ | 时钟触发的 Agent 自动化任务（一次性 / 周期性），JSON 持久化，async 轮询引擎 |
| `crew` | ✅ | 按需委派子 Agent 编排层（TaoLoop 当前使用），支持 planner/researcher/analyst/minimal profile，recursive 嵌套 |
| `subagent` / `delegate` | ✅ | 子 Agent 编排层，`delegate/` 为当前实现，`subagent/` 为向后兼容 shim；支持同步委派、异步派发、并行 Fan-out/Fan-in |
| `agent` | ✅ | 统一 Agent 接口层（`AgentBase` 抽象基类 + `AgentResult`），Planner / Replanner / Executor 均继承 |
| `plan` | ✅ | Plan-and-Execute 多智能体编排：Markdown 计划语言 → IR → 异步 DAG 执行，含 Replanner、资源锁、人类编辑通道、快照回滚、结构化日志 |
| `webui` | ✅ | 工作站仪表板（主页）+ ReAct / Chat 双模式对话 + **Plan 模式**（DAG 可视化、影子编辑器、快照管理、日志流）；服务启停，模块状态总览，知识库独立面板，TTS/STT，Prompt 预览，历史管理 |
| `test` | ✅ | 记忆模块 27 用例 + 工具测试 + plan/ 55 用例（文档解析/快照/日志/通道/编排器）+ delegate/ 15 用例 |

---

## 核心架构

```
用户输入
    │
    ▼
ConvLoop（多轮会话管理）
    │
    ▼
TaoLoop.stream(question)   ← Orchestrator：任务分解 + 工具调用 + 委派
    │
    ├─ bias_query = persona.bias_query(question)   ← 短期偏好偏置 L3 检索方向
    │
    ├─ processor.recall(bias_query)
    │       ├─ L1 短期   → StepsBlock（Human 消息）
    │       ├─ 中期蒸馏  → MemoryBlock（System 消息）
    │       ├─ L3 长期   → 向量检索，含 [DATE] 时间戳
    │       └─ L2 里程碑 → 关键词检索，与 L3 合并注入
    │
    ├─ persona.all_blocks()
    │       → [ProfileBlock, SkillsBlock?,
    │           ReflectionBlock?, PreferenceBlock?]
    │
    ├─ build_messages(...)  →  LLM.stream()  →  parse()
    │       │
    │       ├─ [finish] → FinishEvent → 客户端立即收到答案
    │       │
    │       └─ [tool]   → executor.run(action, args)
    │               │
    │               ├─ 基础工具（calculator / web_search / ...）
    │               ├─ 调度工具（scheduler_add / scheduler_list / scheduler_cancel）
    │               │       └─ → SchedulerEngine（async 事件循环）
    │               │               └─ 到期触发 → TaskRunner（子线程 TaoLoop）
    │               │
    │               └─ 子 Agent 工具（delegate_task / spawn_agent / spawn_all / ...）
    │                       └─ → DelegateManager
    │                               ├─ delegate_task  : 同步运行子 TaoLoop，返回 answer
    │                               ├─ spawn_agent    : 后台线程运行，返回 agent_id
    │                               ├─ spawn_all      : 批量并行（Fan-out）
    │                               ├─ await_agent    : 阻塞等单个完成
    │                               └─ await_all      : 阻塞等全部（Fan-in）
    │
    │               └─ Plan 工具（run_plan / plan_status / plan_pause / plan_skip / ...）
    │                       └─ → PlanOrchestrator（plan/ 模块）
    │                               ├─ PlannerAgent     : Markdown 规划 → PlanDocument IR
    │                               ├─ ReplannerAgent   : 增量上下文重规划
    │                               ├─ _dispatch_all    : 异步 DAG 调度（asyncio.gather）
    │                               │    ├─ 依赖事件等待（asyncio.Event per task）
    │                               │    ├─ 并发限制（asyncio.Semaphore）
    │                               │    ├─ 资源守卫（asyncio.Condition，writes 字段）
    │                               │    └─ 暂停/恢复（_resume_event）
    │                               ├─ HumanEditChannel : shadow.md 文件监视 + patch 队列
    │                               ├─ SnapshotStore    : 计划版本快照 + 回滚
    │                               └─ PlanLogger       : JSONL 结构化日志
    │
    └─ post_process()（后台线程）
            ├─ commit()
            │     ├─ L3 write
            │     ├─ L2 milestone score & write
            │     │     └─ 溢出时按 importance 淘汰 → 迁移写入 L3
            │     └─ evicted milestones → L3.add()
            ├─ trace_store.write()
            ├─ persona.evolve()
            │     └─ 动态层：preference 更新 → PreferenceStore.save()（持久化）
            └─ build_static() → _static_cache（预热下轮）
```

---

## 记忆三层设计

| 层 | 名称 | 检索方式 | 注入方式 | 持久化 |
|---|---|---|---|---|
| L1 | 短期 | 滑动窗口（内存）| ✅ 每步自动 | ❌ |
| — | 中期蒸馏 | LLM 摘要（内存）| ✅ 每问题自动 | ❌ |
| L2 | 里程碑 | 关键词精确子串 + 可选 jieba | ❌ 按需检索（含 detail）| ✅ `milestones.json` |
| L3 | 长期 | FAISS 向量相似度 | ❌ 动态 | ✅ FAISS + JSON |

**L2 溢出策略**：条目数超过 `max_milestones`（默认 50）时，按 importance 从低到高淘汰，被淘汰条目自动迁移写入 L3，确保不丢失任何重要信息。

**L2 中文分词**：`MilestoneRetriever` 优先使用 `jieba`（若已安装），未安装时自动降级为关键词精确子串匹配 + 字符 bigram，LLM 提取的词组级关键词在两种模式下均可有效匹配。

---

## 人格双层设计

| 层 | 名称 | 内容 | 持久化 | 影响 |
|---|---|---|---|---|
| 稳定层 | 长期人格 | 画像 / 技能库 / 自省 | ✅ | Prompt 注入 |
| 动态层 | 近期偏好 | 情绪 / 话题兴趣 / 风格偏移（k 天滑动窗口）| ✅ `preference.json` | L3 检索偏置 + Prompt 注入 |

**近期偏好**：每轮由 LLM 生成带时间戳的 `PreferenceEntry` 快照，滑动窗口（默认 7 天）自动剪枝过期条目，聚合后注入 Prompt；跨会话持久化，重启后自动恢复。

---

## 快速开始

```python
from config.llm_core.config import LLMConfig
from config.react.tao_config import TaoConfig
from llm_core.llm import LLM
from react.action.executor import ActionExecutor
from react.tao import TaoLoop

llm = LLM(LLMConfig(model="gpt-4o", api_key="sk-..."))
executor = ActionExecutor()
cfg = TaoConfig()

loop = TaoLoop(
    llm=llm,
    executor=executor,
    tool_descriptions={"weather": "查询当地天气"},
    cfg=cfg,
)
print(loop.run("今天天气怎么样？"))
```

启动 WebUI：

```bash
# 在仓库根目录下运行
python src/run.py
# 或指定端口
python src/run.py --port 8080
```

---

## 子模块文档

| 文档 | 说明 |
|---|---|
| [react/README.md](./react/README.md) | 完整链路：两层循环、三层记忆、Prompt、Persona、Trace |
| [react/persona/README.md](./react/persona/README.md) | 人格演化引擎详解（稳定层 + 动态层）|
| [react/action/README.md](./react/action/README.md) | 工具注册与 Pydantic 校验，含 Agent 完整工具一览 |
| [react/memory/README.md](./react/memory/README.md) | 三层记忆系统（含 L2 里程碑）|
| [react/prompt/README.md](./react/prompt/README.md) | 块驱动 Prompt 组装 |
| [subagent/README.md](./subagent/README.md) | 子 Agent 编排层（delegate/ 实现 + subagent/ 兼容 shim）|
| [plan/README.md](./plan/README.md) | Plan-and-Execute 多智能体编排：Markdown 计划语言、DAG 调度、Replanner、资源锁、快照、日志 |
| [knowledge/README.md](./knowledge/README.md) | 知识库：MySQL + Redis + Qdrant，三种检索模式 |
| [tts/README.md](./tts/README.md) | TTS / STT 引擎与 Provider 配置 |
| [llm_core/README.md](./llm_core/README.md) | LLM 抽象层 |
| [webui/README.md](./webui/README.md) | Web 界面与 API（含 Plan 模式）|
| [cache/README.md](./cache/README.md) | 本地文件缓存管理 |
| [test/README.md](./test/README.md) | 测试覆盖说明 |
