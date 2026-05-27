# ReAct 工作站 · 项目总览

本仓库定位为 **ReAct Workstation（工作站）**：在单一工程内提供可驻留的智能体运行时、Web 操作台、编排与外围能力（搜索、记忆、语音、子 Agent、可选 Flow DAG 等），便于本地迭代与 Docker 化部署使用同一套代码与配置心智模型。

**工作站目标（概括）**

- **一条启动路径**：`python src/run.py` 拉起 WebUI（默认），可选 CLI、仅检查、或跳过 SearXNG 等模式（见 `src/run.py` 文档字符串）。
- **可操作台**：WebUI 覆盖 ReAct / Chat、Flow（DAG、快照、日志，`/api/flow`）等模式，作为日常交互与观测的主界面（详见 [webui/README.md](./webui/README.md)）。
- **可编排、可自动化**：调度器、子 Agent 委派、`agent.flow` DAG 等与核心推理环在同一架构内联动（见下表「已完成模块」）。
- **可部署栈**：生产/预发可通过 `docker/` 下 Compose 与管理容器落地，并可对接 Prometheus / Loki / Grafana 等（见仓库根目录 [`docker/README.md`](../docker/README.md)）。

下文仍为**技术向总览**：目录结构、数据流、记忆分层与指向各子模块的文档索引。

---

## 技术基础

基于 ReAct（Reasoning + Acting）范式的智能体框架，支持本地 Transformer 推理与 OpenAI 兼容 API；会话上下文由 **`agent/react/context`** 承载，持久记忆与人格等在 **`agent/soul`**，可选 DAG 编排在 **`agent/flow`**。

---

## 项目结构

```
src/
├── config/                  # 所有模块的配置 dataclass
│   ├── llm_core/            # LLMConfig（LLM 核心配置）
│   ├── agent/               # TaoConfig + 各子模块配置
│   │   ├── tao_config.py    #   TaoConfig（顶层）
│   │   ├── persona_config.py
│   │   ├── prompt_config.py
│   │   ├── trace_config.py
│   │   └── memory/          #   MemoryConfig + 各层配置
│   ├── knowledge/           # KnowledgeConfig（遗留；运行时 `src/knowledge/` 包已移除，勿依赖 KB 工具）
│   ├── infra/               # 沙箱 / 数据库 URL（sandbox / bot / bark / ntfy / db.yaml）
│   ├── soul/memory/         # MemoryServiceConfig（Soul 记忆）
│   └── tts/                 # TTS / STT 配置
│
├── infra/                   # 基础设施层
│   ├── llm/                 # LLM 抽象层（本地 Transformers + OpenAI 兼容 API）
│   │   ├── llm.py           #   BaseLLM / CausalLLM / OpenAILLM / LLM
│   │   ├── handle.py        #   LLMHandle（可变转发封装，update() 支持热替换）
│   │   └── service.py       #   LLMService（vLLM 服务管理）
│   ├── network/             # 网络层（搜索引擎 / Bot 协议）
│   │   ├── search/          #   WebSearch（DuckDuckGo / Tavily 等）
│   │   └── bot/             #   Bot 框架（OneBot 协议）
│   ├── sandbox.py           # SandboxManager（文件系统路径验证 + exec_python 受限执行 + HTTP 域名策略）
│   ├── db/                  # RedisClient / MySQLClient（Soul 记忆等）
│   ├── node_runtime.py      # NodeRuntimeManager（节点执行全局线程池单例：executor/verifier/doc 三池）
│   └── searxng_manager.py   # SearXNG 容器管理
│
├── agent/                   # Agent 核心层
│   ├── service.py           # AgentService — SchedulerEngine + TaskRunner + Heartbeat 常驻封装
│   ├── session/             # SessionManager / AgentSession / TaoRequest（多会话 FIFO）
│   ├── adapters/            # FastAPI / WebSocket 与 TaoLoop 桥接
│   ├── base.py              # AgentBase 抽象基类 + AgentResult
│   ├── profile.py           # SubAgentConfig + SubAgentProfile（子 Agent 能力描述）
│   ├── runner.py            # SubAgentRunner（子 Agent 同步执行器）
│   ├── result.py            # AgentResult dataclass
│   ├── soul/                # Soul 子系统（记忆、心跳、生命、人格、当下态、对话编排）
│   │   ├── service.py       #   SoulService 门面
│   │   ├── handlers/        #   api + tao 双通道 handler
│   │   ├── workers/         #   SoulWorkers 后台域任务
│   │   ├── memory/          #   MemoryService / STM-LTM / Retriever / Writers
│   │   ├── heartbeat/       #   HeartbeatModule + HeartbeatOrchestrator
│   │   ├── life/            #   LifeManager / LifeExperienceStack / virtual + anchor
│   │   ├── persona/         #   PersonaManager / buffer / self_concept
│   │   ├── presence/        #   PresenceService / FSM + expectation
│   │   └── speak/           #   SpeakService / compose / io / session
│   ├── react/               # ReAct 核心（TaoLoop / ConvLoop / 工具 / Prompt）
│   │   ├── loop.py          #   ConvLoop
│   │   ├── tao.py           #   TaoLoop
│   │   ├── context/         #   MemoryProcessor + RecentHistoryMemory（会话上下文）
│   │   ├── action/          #   Tool / MCP / Skill
│   │   ├── prompt/          #   Prompt 组装与解析
│   │   └── trace/           #   TraceStore
│   ├── flow/                # DAG / Cluster FlowOrchestrator（无单独长篇文档，见源码与 [agent/react/action](./agent/react/action/README.md) 中 flow 工具）
│
├── runtime/                 # 运行时调度（无 agent 硬依赖）
│   └── scheduler/           # SchedulerEngine / TemporalClock / TaskStore / SchedulerConfig
│
├── tts/                     # 语音合成 / 识别
│   ├── tts/                 # TTSEngine + Edge / OpenAI / Kokoro providers
│   └── stt/                 # STTEngine + OpenAI / faster-whisper providers
│
├── embedding/               # BGE 嵌入模型封装
├── storage/                 # StorageConfig（本地文件根目录配置）
├── webui/                   # Web 前端（FastAPI + 单页 HTML）
├── train/                   # 模型训练（SFT / RL / LoRA / QLoRA）
└── test/                    # 测试套件
```

---

## 已完成模块

| 模块 | 状态 | 说明 |
|---|---|---|
| `infra/llm` | ✅ | 本地推理 + OpenAI API 双后端，流式输出，`backend` 字段路由 |
| `agent/react/action` | ✅ | 工具注册、Pydantic 参数校验、执行调度（Tool / MCP / Skill）|
| `agent/react/context` | ✅ | `MemoryProcessor` + `RecentHistoryMemory`：会话 Step 轨迹 + 中期 JSONL；长期不经 Prompt 自动注入 |
| `agent/soul/memory`（向量 / 里程碑） | ✅ | `LongTermMemory` / `MilestoneMemory`（`agent/soul/memory`）；仅通过 **`memory_recall`** 注入上下文（启用且未仅用 Soul 时可暴露 legacy 后端）|
| `agent/soul/memory`（MemoryService） | ✅ | Redis STM + MySQL LTM、`FlushEngine`、`Retriever`；**`cfg.db`** 启用时 `ingest_turn` 异步写入 |
| `agent/soul/persona` | ✅ | `PersonaManager`（profile / buffer / self_concept）；源码 `agent/soul/persona` |
| `agent/soul/life` | ✅ | `LifeManager` + `LifeExperienceStack`；virtual / anchor 双层 chronicle |
| `agent/soul/presence` | ✅ | `PresenceService`：静态 FSM + 期待 / 冲动 / 分享；与 life/speak 双向绑定 |
| `agent/soul/speak` | ✅ | `SpeakService`：compose → LLM → stream → 体验记账；session 打断队列 |
| `agent/soul/heartbeat` | ✅ | `HeartbeatModule` + `HeartbeatOrchestrator` + `TaskRunner`；与 `SchedulerEngine` 协议对接 |
| `runtime/scheduler` | ✅ | `SchedulerEngine` / `TemporalClock` / `TaskStore`；配置 `SchedulerConfig` + `HeartbeatConfig` |
| `agent/service` | ✅ | `AgentService`：常驻调度 + 心跳组装与生命周期 |
| `agent/session` | ✅ | `SessionManager`：多会话并发、单会话 FIFO |
| `agent/adapters` | ✅ | FastAPI / WebSocket 与 TaoLoop、会话桥接 |
| `infra/db` | ✅ | `RedisClient` / `MySQLClient`，配合 `DBConfig` |
| `agent/react/prompt` | ✅ | 块驱动组装 + `StaticPromptParts` |
| `tts` | ✅ | TTS（Edge / OpenAI / Kokoro）+ STT（OpenAI / faster-whisper）语音模块 |
| `agent/flow` | ✅ | DAG 编排源码（`FlowOrchestrator` 等）；说明散见于 react action / WebUI，无独立长篇文档 |
| `infra/node_runtime` | ✅ | `NodeRuntimeManager` 全局线程池单例：executor_pool（8）/ verifier_pool（4）/ doc_pool（1，FIFO fire-and-forget）|
| `webui` | ✅ | 工作站仪表板 + ReAct / Chat 双模式对话 + Flow 模式（`/api/flow/*`）|
| `test` | ✅ | 记忆模块 + 工具 + agent/flow/ + delegate/ 测试用例 |

---

## 核心架构

```
用户输入
    │
    ▼
ConvLoop（多轮会话管理）
    │
    ▼
TaoLoop.stream(question)
    │
    ├─ processor.recall()
    │       ├─ short_term → StepsBlock（当前会话 Step 轨迹）
    │       └─ medium_term → 中期摘要文本（RecentHistoryMemory / JSONL）
    │
    ├─ persona.all_blocks()
    │       → Profile / Skills / Reflection / Preference / Emotional…
    │       → LifeProfileBlock?（LifeManager）
    │
    ├─ build_messages(...)  →  LLM.stream()  →  parse()
    │       │
    │       ├─ [finish] → FinishEvent → 客户端立即收到答案
    │       │
    │       └─ [tool]   → executor.run(action, args)
    │               │
    │               ├─ 基础与其它工具（calculator / web_search / sandbox / …）
    │               │
    │               ├─ memory_recall（可选）
    │               │       └─ Soul MemoryService 与/或 legacy LTM / 里程碑
    │               │
    │               ├─ 调度工具（scheduler_add / ...）
    │               │       └─ → SchedulerEngine（`runtime.scheduler`，TemporalClock 后台线程）
    │               │
    │               ├─ 子 Agent（delegate_task）
    │               │       └─ → SubAgentRunner → 嵌套 TaoLoop
    │               │
    │               └─ Flow 工具（run_flow / flow_wait / ...）
    │                       └─ → FlowOrchestrator（DAG 编排）
    │
    └─ post_process()（后台线程）
            ├─ processor.commit() → 中期 JSONL
            ├─ MemoryService.ingest_turn()（若 cfg.db 启用）
            ├─ 周期性 consolidation → legacy LongTermMemory（若启用且 consolidation_k>0）
            ├─ trace_store.write()
            ├─ persona.evolve()
            └─ build_static() → _static_cache（预热下轮）
```

---

## 记忆与上下文（现行）

| 类别 | 组件 | 注入 Prompt | 持久化 |
|---|---|---|---|
| 会话轨迹 | `MemoryProcessor` / `Step` | ✅ 每步 StepsBlock | ❌ |
| 中期摘要 | `RecentHistoryMemory` | ✅ `medium_term` 文本 | ✅ `medium_term.jsonl` |
| 向量长期 / 里程碑 | `LongTermMemory` / `MilestoneMemory`（soul 包） | ❌ 默认不注入；靠 **`memory_recall`** | ✅ `memories.json` + `qdrant/` 等 |
| Soul 单元记忆 | `MemoryService`（STM/LTM） | ❌ 默认不注入；靠 **`memory_recall`** 或业务拼装 | ✅ Redis + MySQL |

旧的 **`agent/react/memory/`** 目录与独立 **`docs/knowledge`**、**`docs/plan`** 长篇说明已移除；编排请参阅 **`agent/react/action`**（flow 工具）与 **`src/agent/flow`** 源码。

---

## 快速开始

```python
from config.llm_core.config import LLMConfig
from config.agent.tao_config import TaoConfig
from infra.llm import LLM, LLMHandle
from agent.react.action.manager import ToolManager
from agent.react.tao import TaoLoop

llm = LLM(LLMConfig(model="gpt-4o", api_key="sk-...", backend="openai"))
tool_manager = ToolManager()
executor = tool_manager.build_executor()
cfg = TaoConfig()

loop = TaoLoop(
    llm=LLMHandle(llm),
    executor=executor,
    tool_descriptions=tool_manager.primary_descriptions(),
    cfg=cfg,
    tool_category_summary=tool_manager.category_summary(),
)

for event in loop.stream("今天天气怎么样？"):
    print(event)
```

启动 WebUI：

```bash
python src/run.py
# 或指定端口
python src/run.py --port 8080
```

---

## 子模块文档

| 文档 | 说明 |
|---|---|
| [infra/llm/README.md](./infra/llm/README.md) | LLM 抽象层（本地 + OpenAI，`backend` 字段路由）|
| [agent/README.md](./agent/README.md) | 子 Agent 委派层（SubAgentConfig / SubAgentRunner / DelegateTaskSkill）|
| [agent/soul/README.md](./agent/soul/README.md) | Soul 子系统总索引（memory / heartbeat / life / persona / presence / speak）|
| [agent/soul/speak/README.md](./agent/soul/speak/README.md) | `SpeakService`：compose / io / session / drive |
| [agent/soul/presence/README.md](./agent/soul/presence/README.md) | `PresenceService`：当下态 FSM + 期待 / 冲动 |
| [agent/soul/memory/README.md](./agent/soul/memory/README.md) | Soul `MemoryService`：STM/LTM、写入器、检索与冲刷 |
| [agent/react/README.md](./agent/react/README.md) | TaoLoop / ConvLoop、与 Soul / 调度 / Flow 的接线说明 |
| [agent/react/context/README.md](./agent/react/context/README.md) | 会话上下文：`MemoryProcessor`、`RecentHistoryMemory` |
| [agent/react/action/README.md](./agent/react/action/README.md) | 工具与 Skill（含 `run_flow` / `flow_*`）|
| [agent/react/prompt/README.md](./agent/react/prompt/README.md) | Prompt 组装与解析 |
| [agent/react/persona/README.md](./agent/react/persona/README.md) | 重定向：`PersonaManager` 详见 [agent/soul/persona/README.md](./agent/soul/persona/README.md) |
| [agent/soul/persona/README.md](./agent/soul/persona/README.md) | 人格演化（profile / buffer / self_concept），源码 `agent/soul/persona` |
| [agent/soul/heartbeat/README.md](./agent/soul/heartbeat/README.md) | HeartbeatModule + HeartbeatOrchestrator 与调度对接 |
| [agent/soul/life/README.md](./agent/soul/life/README.md) | LifeManager、`LifeExperienceStack`、virtual / anchor 层 |
| [runtime/README.md](./runtime/README.md) | `runtime.scheduler`：SchedulerEngine、TemporalClock |
| [agent/service/README.md](./agent/service/README.md) | AgentService 常驻封装 |
| [agent/session/README.md](./agent/session/README.md) | SessionManager 多会话模型 |
| [agent/adapters/README.md](./agent/adapters/README.md) | FastAPI / 流式桥接 |
| [infra/db/README.md](./infra/db/README.md) | Redis / MySQL 客户端 |
| [tts/README.md](./tts/README.md) | TTS / STT 引擎与 Provider 配置 |
| [webui/README.md](./webui/README.md) | Web 界面与 API（含 Flow `/api/flow`）|
| [storage/README.md](./storage/README.md) | 运行时本地文件布局与路径配置 |
| [config/README.md](./config/README.md) | 配置 dataclass 结构 |
| [test/README.md](./test/README.md) | 测试覆盖说明 |
