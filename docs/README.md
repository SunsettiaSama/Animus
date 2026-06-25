# 栖灵 Animus

> 一个会思考、会行动、会记得、会成长的驻留型智能体平台。

**栖灵（Animus）** 不是普通聊天机器人，也不只是一个 ReAct demo。它试图把「完成任务的能力」和「长期存在的主体性」放进同一套工程系统：智能体可以通过工具完成复杂任务，也可以在长期交互中积累记忆、形成画像、维护当下状态，并在合适的时候主动出现。

如果说多数 Agent 框架关注“这一轮怎么答好”，栖灵关注的是：**一个智能体如何持续生活、持续记得、持续与人建立关系，同时仍然能做事。**

---

## 核心亮点

| 能力 | 栖灵提供什么 |
|---|---|
| **任务执行** | ReAct 推理循环、工具调用、流程编排、子任务委派 |
| **长期记忆** | 对话工作记忆、经历压缩、长期记忆、关系画像 |
| **人格演化** | 稳定 persona、自我认知、交互者画像、风格约束 |
| **生活叙事** | 将对话和事件沉淀为体验、手账、生活线索 |
| **主动性** | presence / heartbeat 驱动的冲动、期待、主动触达 |
| **产品化** | Web 控制台、WebSocket 流式对话、配置化 LLM、Docker 部署 |

---

## 系统蓝图

栖灵可以理解为三层结构：外层面向用户和运维，中层维护主体性，内层负责推理与行动。

```text
┌──────────────────────────────────────────────┐
│  Web / Service Layer                         │
│  控制台 · HTTP / WebSocket · 多会话 · 部署观测 │
└──────────────────────┬───────────────────────┘
                       │
┌──────────────────────▼───────────────────────┐
│  Soul Layer                                   │
│  Memory · Persona · Life · Presence · Speak   │
└──────────────────────┬───────────────────────┘
                       │
┌──────────────────────▼───────────────────────┐
│  Reasoning Layer                              │
│  ReAct Loop · Tools · Flow · Delegation        │
└──────────────────────────────────────────────┘
```

### Reasoning Layer

负责任务型智能：理解目标、拆解步骤、选择工具、观察结果、继续推理，直到形成最终回答或完成操作。

主要入口：

- [agent/react/README.md](./agent/react/README.md)：ReAct 推理循环
- [agent/react/action/README.md](./agent/react/action/README.md)：工具、MCP、Skill、Flow
- [agent/react/context/README.md](./agent/react/context/README.md)：任务上下文与压缩

### Soul Layer

负责“这个智能体是谁、记得什么、当下处于什么状态、要不要主动开口”。Soul 不是单个模块，而是一组协作域：

| 域 | 职责 |
|---|---|
| **Memory** | 保存事实、经历、关系与可被唤起的长期记忆 |
| **Persona** | 维护人格、偏好、自我叙事与对交互者的画像 |
| **Life** | 将重要交互整理为体验、手账和生活叙事 |
| **Presence** | 表示当下的感受、期待、冲动和主动性 |
| **Speak** | 将记忆、人格、场景和引导组合成自然对话 |
| **Heartbeat** | 后台节律：整理、反思、推进演化任务 |

总览见 [agent/soul/README.md](./agent/soul/README.md)。

### Web / Service Layer

面向实际使用和接入：浏览器控制台、HTTP API、WebSocket 流式输出、服务生命周期、Docker 部署。

入口：

- [webui/README.md](./webui/README.md)：Web 控制台与 API
- [agent/service/README.md](./agent/service/README.md)：常驻服务与心跳组装
- [../docker/README.md](../docker/README.md)：容器部署

---

## 一次典型运行

1. 用户在 Web 控制台发来一条消息。
2. Speak 打开或复用会话，读取当前 session 状态、近期对话、persona、presence 和 memory。
3. Orchestrator / directors 生成这一轮的交付计划：要不要说、说什么、分几段、等待多久。
4. Delivery executor 通过 WebSocket 把分段回复推到前端。
5. 对话结果写入 Life，触发 memory / persona / presence 的后续更新。
6. Heartbeat 在后台继续整理体验、刷新叙事，并判断未来是否需要主动出现。

这条链路让它看起来不只是“回答问题”，而是在一个持续存在的主体里发生了一次新的经历。

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

轻量环境可参考 `requirements-light.txt`，本地语音能力可参考 `requirements-voice-local.txt`。

### 2. 配置 LLM

仓库默认忽略 `config/` 下的本地配置文件。你需要按自己的模型服务准备配置，常见路径包括：

```text
config/llm_core/config.yaml
```

配置结构说明见 [config/README.md](./config/README.md)，LLM 接入见 [infra/llm/README.md](./infra/llm/README.md)。

### 3. 启动 Web 控制台

```bash
python src/run.py
```

启动后在浏览器中打开控制台即可对话。容器化部署见 [docker/README.md](../docker/README.md)。

---

## 项目结构

```text
src/
├── agent/
│   ├── react/       # ReAct 推理、工具调用、任务上下文
│   ├── soul/        # Memory / Persona / Life / Presence / Speak / Heartbeat
│   ├── service/     # 常驻服务装配
│   ├── session/     # 多会话管理
│   └── adapters/    # 外部接入适配
├── webui/           # Web 控制台、HTTP API、WebSocket
├── infra/           # LLM、数据库等基础设施
├── runtime/         # 调度与时间任务
├── config/          # 配置结构
└── run.py           # 统一启动入口
```

---

## 文档导航

### 智能体核心

| 文档 | 内容 |
|---|---|
| [agent/README.md](./agent/README.md) | Agent 总体结构与子智能体委派 |
| [agent/react/README.md](./agent/react/README.md) | ReAct 推理循环 |
| [agent/react/action/README.md](./agent/react/action/README.md) | 工具注册、MCP、Skill、Flow |
| [agent/react/context/README.md](./agent/react/context/README.md) | 会话内上下文与中期摘要 |
| [agent/react/prompt/README.md](./agent/react/prompt/README.md) | 提示词组装与解析 |

### Soul 主体性

| 文档 | 内容 |
|---|---|
| [agent/soul/README.md](./agent/soul/README.md) | Soul 总览与域间关系 |
| [agent/soul/memory/README.md](./agent/soul/memory/README.md) | 记忆：经历如何被保存与唤起 |
| [agent/soul/persona/README.md](./agent/soul/persona/README.md) | 人格：画像、偏好与自我认知 |
| [agent/soul/life/README.md](./agent/soul/life/README.md) | 生活：体验、手账与叙事 |
| [agent/soul/presence/README.md](./agent/soul/presence/README.md) | 当下态：感受、期待与主动触达 |
| [agent/soul/speak/README.md](./agent/soul/speak/README.md) | 对话：编排、流式输出与记账 |
| [agent/soul/heartbeat/README.md](./agent/soul/heartbeat/README.md) | 心跳：后台节律与演化任务 |

### 运行与基础设施

| 文档 | 内容 |
|---|---|
| [webui/README.md](./webui/README.md) | Web 控制台与 HTTP API |
| [agent/service/README.md](./agent/service/README.md) | 常驻服务与心跳组装 |
| [agent/session/README.md](./agent/session/README.md) | 多会话管理 |
| [agent/adapters/README.md](./agent/adapters/README.md) | FastAPI / WebSocket 接入 |
| [runtime/README.md](./runtime/README.md) | 调度与时间任务 |
| [infra/llm/README.md](./infra/llm/README.md) | 大模型接入 |
| [infra/db/README.md](./infra/db/README.md) | 数据库客户端 |
| [tts/README.md](./tts/README.md) | 语音合成与识别 |
| [storage/README.md](./storage/README.md) | 本地数据目录 |
| [config/README.md](./config/README.md) | 配置项结构 |
| [test/README.md](./test/README.md) | 测试说明 |

---

## 当前状态

栖灵仍处于快速迭代阶段。核心链路已经具备可运行形态，但部分模块仍在重构中，尤其是长期记忆、Speak 编排、主动性和前端体验之间的衔接。

适合现在使用它的人：

- 想研究长期智能体、人格化 Agent、主动对话和记忆系统的开发者
- 希望基于现有框架二次开发私有智能体产品的团队
- 想把 ReAct 工具执行和长期关系体验放进同一个系统的人

如果你只需要一个轻量聊天 UI，这个项目可能过重；如果你想研究“一个智能体如何持续存在”，这里正是它的实验场。
