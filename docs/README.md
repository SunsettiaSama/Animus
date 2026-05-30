# 栖灵 Animus

> 不只是一次对话，而是一个会成长、会记得、会主动出现的智能体。

**栖灵（Animus）** 是一套**可长期驻留**的智能体运行平台。它把「推理与行动」和「记忆、人格、生活叙事」放在同一套系统里，让你部署的不只是一个聊天窗口，而是一个**有连续性的数字主体**——能记住过往、随时间演化，并在合适的时刻主动开口。

*Animus* 取意「内在驱力、灵魂」；*栖灵* 取意「在此栖居的灵」——既点出驻留型架构，也呼应 Soul 主体性设计。

---

## 我们在解决什么问题

大多数智能体产品停留在「问一句、答一句」：每次对话彼此独立，没有真正的延续感，也难以承载复杂任务与长期关系。

栖灵想做的，是把下面几件事合成一体：

| 你需要的 | 栖灵提供的 |
|---|---|
| 能完成复杂任务 | 推理 + 工具调用 + 子任务委派 + 流程编排 |
| 能记住重要的事 | 分层记忆：当下对话、中期摘要、长期经历与人际关系 |
| 有稳定的人格与风格 | 画像、偏好、自我认知随交互缓慢演化 |
| 像「活着」而不只是「响应」 | 内在状态、生活叙事、心跳与主动触达 |
| 能落地、能运维 | Web 控制台、本地或容器部署、可观测与配置化 |

---

## 蓝图：三层能力

可以把整个系统想象成三层同心结构——外层负责**做事**，中层负责**成为谁**，内层负责**持续运转**。

```
        ┌─────────────────────────────────────┐
        │  栖灵 · 交互与运维                    │
        │  Web 控制台 · 多会话 · 部署与观测      │
        └──────────────────┬──────────────────┘
                           │
        ┌──────────────────▼──────────────────┐
        │  Soul · 主体性                        │
        │  记忆 · 人格 · 生活 · 当下态 · 对话    │
        └──────────────────┬──────────────────┘
                           │
        ┌──────────────────▼──────────────────┐
        │  推理与行动                           │
        │  思考 → 选工具 → 执行 → 再思考         │
        └─────────────────────────────────────┘
```

### 推理与行动

智能体的「工作模式」：理解问题、拆解步骤、调用搜索/计算/代码/委派等能力，直到给出结果。适合问答、调研、自动化操作等**任务型**场景。（实现上采用 ReAct 范式，详见技术文档。）

→ 深入了解：[agent/react/README.md](./agent/react/README.md)

### 主体性（Soul）

智能体的「生命模式」：跨会话保留记忆与人格，积累生活经历，维护当下的情绪与状态；在心跳驱动下持续整理、反思，必要时**主动发起对话**。

Soul 包含五个彼此配合的能力域：

| 能力 | 一句话 |
|---|---|
| **记忆** | 记住事实、关系与经历，需要时再想起 |
| **人格** | 稳定的性格、偏好与自我认知，随时间缓慢变化 |
| **生活** | 把日常体验整理成可读的「生活史」 |
| **当下态** | 此刻的感受、期待与冲动——决定是否该开口 |
| **对话** | 把记忆与人格自然融入每一轮交流 |

→ 总览：[agent/soul/README.md](./agent/soul/README.md)

### 控制台

面向使用者的「驾驶舱」：在浏览器里对话、切换模式、查看运行状态；同一套代码可在本机调试，也可通过 Docker 部署到生产环境。

→ 界面与 API：[webui/README.md](./webui/README.md) · 容器部署：[../docker/README.md](../docker/README.md)

---

## 一次典型经历（故事线）

**早晨**，用户通过 Web 界面发来一条消息。系统先读取当前对话上下文，再按需调取相关记忆与人格设定，组织成完整的提示，交给大模型推理。

**推理过程中**，智能体可能搜索资料、运行代码、把子任务交给专门的子智能体，或启动一条预定义的流程（Flow）——用户不必关心内部步骤，只需看到流式输出的进展与最终结果。

**对话结束后**，这一轮经历会被记入生活体验栈；显著的内容擢升为长期记忆；人格与偏好做小幅更新；内在状态（当下态）随之调整。

**白天**，心跳在后台按节奏运行：整理记忆、推进生活叙事、扫描是否该主动分享或开口。

**傍晚**，用户再次打开界面——智能体记得之前的交流，语气与关系感保持一致，而不是从零开始的陌生人。

这就是栖灵想交付的体验：**任务能力 + 关系连续性 + 可运维的产品形态**。

---

## 快速上手

**启动 Web 控制台（推荐）**

```bash
python src/run.py
```

浏览器打开即可开始对话。更多启动选项见仓库根目录 [`README.md`](../README.md)。

**开发者最小示例**（在代码中驱动一轮推理）

```python
from config.llm_core.config import LLMConfig
from config.agent.tao_config import TaoConfig
from infra.llm import LLM, LLMHandle
from agent.react.action.manager import ToolManager
from agent.react.tao import TaoLoop

llm = LLM(LLMConfig(model="gpt-4o", api_key="sk-...", backend="openai"))
tools = ToolManager()
loop = TaoLoop(
    llm=LLMHandle(llm),
    executor=tools.build_executor(),
    tool_descriptions=tools.primary_descriptions(),
    cfg=TaoConfig(),
    tool_category_summary=tools.category_summary(),
)

for event in loop.stream("今天适合做什么？"):
    print(event)
```

配置说明见 [config/README.md](./config/README.md)。

---

## 文档导航

按需进入对应章节；各文档保留实现细节，本页只做门面与路线指引。

### 智能体核心

| 文档 | 适合谁 | 内容 |
|---|---|---|
| [agent/README.md](./agent/README.md) | 集成方、架构师 | Agent 总体结构与子智能体委派 |
| [agent/react/README.md](./agent/react/README.md) | 开发者 | 推理循环、工具、与 Soul 的协作方式 |
| [agent/react/action/README.md](./agent/react/action/README.md) | 开发者 | 工具注册、MCP、Skill、Flow 工具 |
| [agent/react/context/README.md](./agent/react/context/README.md) | 开发者 | 会话内上下文与中期摘要 |
| [agent/react/prompt/README.md](./agent/react/prompt/README.md) | 开发者 | 提示词组装与解析 |

### Soul · 主体性

| 文档 | 内容 |
|---|---|
| [agent/soul/README.md](./agent/soul/README.md) | Soul 总览与域间关系 |
| [agent/soul/memory/README.md](./agent/soul/memory/README.md) | 记忆：经历如何被记住与唤起 |
| [agent/soul/persona/README.md](./agent/soul/persona/README.md) | 人格：画像、偏好与自我认知 |
| [agent/soul/life/README.md](./agent/soul/life/README.md) | 生活：体验、手账与叙事 |
| [agent/soul/presence/README.md](./agent/soul/presence/README.md) | 当下态：感受、期待与主动触达 |
| [agent/soul/speak/README.md](./agent/soul/speak/README.md) | 对话：编排、流式输出与记账 |
| [agent/soul/heartbeat/README.md](./agent/soul/heartbeat/README.md) | 心跳：后台节律与演化任务 |

### 运行、接入与基础设施

| 文档 | 内容 |
|---|---|
| [webui/README.md](./webui/README.md) | Web 控制台与 HTTP API |
| [agent/service/README.md](./agent/service/README.md) | 常驻服务与心跳组装 |
| [agent/session/README.md](./agent/session/README.md) | 多会话管理 |
| [agent/adapters/README.md](./agent/adapters/README.md) | FastAPI / WebSocket 接入 |
| [runtime/README.md](./runtime/README.md) | 调度与时间任务 |
| [infra/llm/README.md](./infra/llm/README.md) | 大模型接入（本地 / OpenAI 兼容）|
| [infra/db/README.md](./infra/db/README.md) | 数据库客户端 |
| [tts/README.md](./tts/README.md) | 语音合成与识别 |
| [storage/README.md](./storage/README.md) | 本地数据目录说明 |
| [config/README.md](./config/README.md) | 配置项结构 |
| [test/README.md](./test/README.md) | 测试说明 |

---

## 适合什么样的客户

- **需要「有记忆、有人格」的 AI 产品**，而不只是 API 套壳
- **希望任务自动化与长期陪伴/服务**在同一技术栈内实现
- **重视私有化部署与可扩展**，从单机验证到容器化生产
- **愿意基于栖灵二次开发**，而非从零拼装记忆、调度、UI

如果你正在评估类似方向，建议从 [Web 控制台](./webui/README.md) 或 [Soul 总览](./agent/soul/README.md) 读起，再按需深入具体模块。

---

## 技术说明（给工程师的一行索引）

完整源码位于 `src/`。推理环在 `agent/react/`，Soul 主体性在 `agent/soul/`，Web 在 `webui/`，配置在 `config/`。
