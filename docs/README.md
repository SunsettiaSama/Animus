# ReAct 工作站 · 项目总览

本仓库定位为 **ReAct Workstation（工作站）**：在单一工程内提供可驻留的智能体运行时、Web 操作台、编排与外围能力（搜索、记忆、知识库、语音、计划 DAG、子 Agent 等），便于本地迭代与 Docker 化部署使用同一套代码与配置心智模型。

**工作站目标（概括）**

- **一条启动路径**：`python src/run.py` 拉起 WebUI（默认），可选 CLI、仅检查、或跳过 SearXNG 等模式（见 `src/run.py` 文档字符串）。
- **可操作台**：WebUI 覆盖 ReAct / Chat、Flow（DAG、快照、日志，`/api/flow`）等模式，作为日常交互与观测的主界面（详见 [webui/README.md](./webui/README.md)）。
- **可编排、可自动化**：Plan-and-Execute、调度器、子 Agent 委派等与核心推理环在同一架构内联动（见下表「已完成模块」）。
- **可部署栈**：生产/预发可通过 `docker/` 下 Compose 与管理容器落地，并可对接 Prometheus / Loki / Grafana 等（见仓库根目录 [`docker/README.md`](../docker/README.md)）。

下文仍为**技术向总览**：目录结构、数据流、记忆分层与指向各子模块的文档索引。

---

## 技术基础

基于 ReAct（Reasoning + Acting）范式的智能体框架，支持本地 Transformer 推理与 OpenAI 兼容 API，集成四层记忆系统、人格演化引擎与可扩展动作空间。

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
│   ├── knowledge/           # 知识库配置（MySQL / Redis / Qdrant / 嵌入）
│   ├── infra/               # 沙箱等基础设施配置（sandbox / bot / bark / ntfy）
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
│   ├── node_runtime.py      # NodeRuntimeManager（节点执行全局线程池单例：executor/verifier/doc 三池）
│   └── searxng_manager.py   # SearXNG 容器管理
│
├── agent/                   # Agent 核心层
│   ├── base.py              # AgentBase 抽象基类 + AgentResult
│   ├── profile.py           # SubAgentConfig + SubAgentProfile（子 Agent 能力描述）
│   ├── runner.py            # SubAgentRunner（子 Agent 同步执行器）
│   ├── result.py            # AgentResult dataclass
│   ├── react/               # ReAct 核心框架
│   │   ├── loop.py          #   ConvLoop — 外层多轮对话循环
│   │   ├── tao.py           #   TaoLoop  — 内层 TAO 推理循环
│   │   ├── parser.py        #   re-export prompt/parser.py 公共符号
│   │   ├── factory.py       #   build_conv_loop 工厂函数
│   │   ├── action/          #   动作空间（Tool / MCP / Skill）
│   │   ├── memory/          #   四层记忆系统（L1 / L2 / 里程碑 / L3）
│   │   ├── prompt/          #   块驱动 Prompt 组装（含 parser 实现）
│   │   ├── persona/         #   人格演化（稳定层 + 动态层 + 情绪层）
│   │   ├── life/            #   生活状态子系统（活动日志 + 日度综合）
│   │   └── trace/           #   推理链存档
│   ├── flow/                # Flow 编排（agent.flow.base 泛化 DAG + 实现层）
│   │   ├── base/            #   DAG 抽象（就绪集、拓扑宽度等）
│   │   │   └── components/  #   节点核心组件（新三接口体系）
│   │   │       ├── node_spec.py     #     NodeManifest（节点静态合同，frozen dataclass）
│   │   │       ├── runtime.py       #     RunnableNode / NodeResult / NodeExecutionContext / LogEntry
│   │   │       ├── protocols.py     #     ManifestExecutor / NodeVerifier / NodeDocumentWriter / NodeObserver / NodeMutator
│   │   │       ├── observation.py   #     NodeObservation / TaoStep / ObservationMode（full / distilled）
│   │   │       └── verification.py  #     VerificationResult / VerificationCheck（abstract + concrete 两类校验）
│   │   ├── document.py      #   PlanDocument IR（PlanTask/PlanModule）
│   │   ├── orchestrator.py  #   FlowOrchestrator
│   │   └── ...
│   └── scheduler/           # 时钟触发 Agent 自动化任务
│       ├── config.py
│       ├── task.py
│       ├── store.py
│       ├── engine.py
│       ├── runner.py
│       └── timeline.py
│
├── knowledge/               # 知识库（MySQL + Redis + Qdrant）
│   ├── store.py             # MySQL CRUD
│   ├── vector_store.py      # Qdrant 向量索引
│   ├── cache.py             # Redis 缓存
│   ├── embedder.py          # BGE 嵌入模型
│   ├── ingestion.py         # 分块 → 嵌入 → MySQL + Qdrant
│   └── retriever.py         # keyword / semantic / hybrid 三种检索
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
| `agent/react/memory/short_term` | ✅ | Token 级滑动窗口 L1 短期记忆 + LLM 蒸馏 |
| `agent/react/memory/medium_term` | ✅ | 跨 session JSONL Q&A 历史（L2），LLM 滚动整合 |
| `agent/react/memory/long_term` | ✅ | L3 BGE + Qdrant（本地嵌入式），时间戳感知，五场景自动检索（含 TIMELINE）|
| `agent/react/memory/milestone` | ✅ | 里程碑，LLM 重要性评分，关键词精确匹配（jieba 可选），溢出迁移 L3 |
| `agent/react/prompt` | ✅ | 块驱动组装 + `StaticPromptParts` 静态缓存预热 |
| `agent/react/persona/profile` | ✅ | 人物画像 + 技能库 + 自省（IROTE），LLM 演化引擎 |
| `agent/react/persona/preference` | ✅ | 短期偏好动态层（话题兴趣 / 风格偏移），影响 L3 检索偏置 + Prompt 注入 |
| `agent/react/persona/emotional` | ✅ | 叙事情感层（锚点 + 纹理文本），LLM 演化，`EmotionalStateBlock` 注入 Prompt |
| `agent/react/trace` | ✅ | 推理链存档（`.react/traces/`）|
| `agent/react/loop` | ✅ | ConvLoop + TaoLoop 两层循环，异步后台提交，Prompt 预热 |
| `agent/react/life` | ✅ | 生活状态子系统：活动叙事日志（LifeLog）、LLM 生成生活画像（LifeProfile）、日度综合（DailySynthesizer）|
| `agent` | ✅ | SubAgentConfig / SubAgentProfile / SubAgentRunner + `DelegateTaskSkill`（同步子 Agent 委派）|
| `agent/scheduler` | ✅ | 时钟触发的 Agent 自动化任务（一次性 / 周期性），JSON 持久化，async 轮询引擎 |
| `knowledge` | ✅ | MySQL 文档存储 + Qdrant 向量索引 + Redis 缓存，keyword / semantic / hybrid 三种检索 |
| `tts` | ✅ | TTS（Edge / OpenAI / Kokoro）+ STT（OpenAI / faster-whisper）语音模块 |
| `agent/flow` | ✅ | Flow 编排：`agent.flow.base` 泛化 DAG + Plan-and-Execute 实现、DAG 调度、Replanner、快照、日志 |
| `agent/flow/base/components` | ✅ | 节点新三接口体系：`NodeManifest`（静态合同）/ `RunnableNode`（`run` / `review` / `modify`）/ `ManifestExecutor` + `NodeVerifier`（TAO 纠错循环）/ `NodeDocumentWriter`（异步落盘）|
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
    ├─ persona.bias_query(question)   ← 近期偏好偏置 L3 检索方向
    │
    ├─ processor.recall(bias_query)
    │       ├─ L1 短期   → StepsBlock + DistillateBlock（Human 消息）
    │       ├─ L2 中期   → MemoryBlock（System 消息，跨 session JSONL 历史）
    │       ├─ L3 长期   → 向量检索，含 [DATE] 时间戳
    │       └─ 里程碑    → 关键词检索，与 L3 合并注入
    │
    ├─ persona.all_blocks()
    │       → [ProfileBlock, SkillsBlock?, ReflectionBlock?, PreferenceBlock?, EmotionalStateBlock?]
    │       → [LifeProfileBlock?]
    │
    ├─ build_messages(...)  →  LLM.stream()  →  parse()
    │       │
    │       ├─ [finish] → FinishEvent → 客户端立即收到答案
    │       │
    │       └─ [tool]   → executor.run(action, args)
    │               │
    │               ├─ 基础工具（calculator / web_search / ...）
    │               │
    │               ├─ 调度工具（scheduler_add / ...）
    │               │       └─ → SchedulerEngine（async 事件循环）
    │               │
    │               ├─ 子 Agent（delegate_task）
    │               │       └─ → SubAgentRunner → 嵌套 TaoLoop
    │               │
    │               └─ Flow 工具（run_flow / flow_wait / ...）
    │                       └─ → FlowOrchestrator（DAG 编排）
    │
    └─ post_process()（后台线程）
            ├─ commit()  → L2 JSONL / L3 Qdrant / 里程碑
            ├─ trace_store.write()
            ├─ persona.evolve()
            └─ build_static() → _static_cache（预热下轮）
```

---

## 记忆四层设计

| 层 | 名称 | 检索方式 | 持久化 |
|---|---|---|---|
| L1 | 短期（滑动窗口）| 内存，每步自动 | ❌ |
| L1 蒸馏 | 短期蒸馏摘要 | LLM 压缩（内存）| ❌ |
| L2 | 中期（跨 session Q&A 历史）| JSONL 按时间窗口加载 | ✅ `medium_term.jsonl` |
| 里程碑 | 重要事件 | 关键词精确子串 + jieba | ✅ `milestones.json` |
| L3 | 长期 | Qdrant 向量相似度（含时间线模式）| ✅ `qdrant/` + `memories.json` |

---

## 快速开始

```python
from config.llm_core.config import LLMConfig
from config.agent.tao_config import TaoConfig
from infra.llm import LLM
from agent.react.action.manager import ToolManager
from agent.react.tao import TaoLoop

llm = LLM(LLMConfig(model="gpt-4o", api_key="sk-...", backend="openai"))
tool_manager = ToolManager()
executor = tool_manager.build_executor()
cfg = TaoConfig()

loop = TaoLoop(
    llm=llm,
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
| [agent/react/README.md](./agent/react/README.md) | 完整链路：两层循环、四层记忆、Prompt、Persona、Trace |
| [agent/react/action/README.md](./agent/react/action/README.md) | 工具注册与 Pydantic 校验，含 Agent 完整工具一览 |
| [agent/react/memory/README.md](./agent/react/memory/README.md) | 四层记忆系统 |
| [agent/react/prompt/README.md](./agent/react/prompt/README.md) | 块驱动 Prompt 组装 |
| [agent/react/persona/README.md](./agent/react/persona/README.md) | 人格演化引擎详解（稳定层 + 动态层 + 情绪层）|
| [plan/README.md](./plan/README.md) | Flow（`agent.flow`）编排说明：Markdown 计划语言、DAG、Replanner（文档路径沿用 plan）|
| [knowledge/README.md](./knowledge/README.md) | 知识库：MySQL + Redis + Qdrant，三种检索模式 |
| [tts/README.md](./tts/README.md) | TTS / STT 引擎与 Provider 配置 |
| [webui/README.md](./webui/README.md) | Web 界面与 API（含 Flow `/api/flow`）|
| [storage/README.md](./storage/README.md) | 运行时本地文件布局与路径配置 |
| [config/README.md](./config/README.md) | 配置 dataclass 结构 |
| [test/README.md](./test/README.md) | 测试覆盖说明 |
