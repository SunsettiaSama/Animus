# agent/react

`src/agent/react/` 是通用 ReAct 会话实现，当前服务于 CLI、legacy WebUI ReAct 和部分
AgentService/Scheduler 路径。Soul/Speak 主对话有独立的会话、Prompt、Memory 和 LLM
编排，**不经过 `ConvLoop` 或 `TaoLoop`**。确认后的真实工作使用 `src/worker/react/`。

## 模块边界

```text
agent/react/
  loop.py                  ConvLoop：会话外壳
  tao.py                   TaoLoop：Thought/Action/Observation 循环
  factory.py               AppState -> ConvLoop；唯一常规 RiskGate 装配点
  context/                 当前轮 Step + medium-term JSONL
  prompt/                  ReAct 消息组装、解析和修复
  action/                  Tool / Skill / MCP / RiskGate
  trace/                   推理轨迹落盘
```

`worker/react/` 保留相同的 ReAct 核心，但额外接收 `AgentStateService`。Worker 每轮开始读取
`worker_portrait`、`reflection_portrait`、`memory_portrait`，创建 `TurnTaskGraph` 并注入
system prompt；每次工具调用更新任务图，轮后异步提交工作反思。`agent/react` 没有这条
Worker AgentState 链。

## 入口与调用链

### CLI

`src/run.py::_build_tao()` 直接构造 `agent.react.tao.TaoLoop`，`run_cli()` 调用
`tao.run(question)`。这里没有 `ConvLoop`、`SessionManager`，也没有 factory 注入的
RiskGate、默认 SubAgent 或默认 Flow。

### legacy WebUI

```text
POST /api/react/init
  -> agent.adapters.react_bridge.do_react_init
  -> agent.react.factory.build_conv_loop
  -> SessionManager.create_session("webui", ConvLoop)

/ws/react/run 或 /api/react/run
  -> TaoRequest
  -> AgentSession FIFO worker
  -> ConvLoop.stream
  -> TaoLoop.stream
```

该 API 明确标记 deprecated；WebUI 主入口是 `/ws/speak/run`。

### Scheduler、SubAgent、Flow

- factory 默认给 TaoConfig 配置 Scheduler、SubAgent 和 Flow，并可复用全局
  `SchedulerEngine`。
- `delegate_task` 同步调用 `agent.runner.SubAgentRunner`，返回 answer 后主 TaoLoop 才继续。
- `run_flow` 异步启动 cluster Flow；`flow_status`、`flow_wait`、`flow_skip` 操作当前 Flow。
- Scheduler 定时任务通过 `runtime.scheduler.SchedulerEngine` 和
  `agent.soul.heartbeat.task_runner.TaskRunner` 执行，不等同于 Soul heartbeat。

## TaoLoop 单步数据流

```text
question
  -> MemoryProcessor.recall()
       short_term = 当前问题已执行的 Step
       medium_term = RecentHistoryMemory.render()
  -> PromptManager
       system = ReAct role + 工具说明 + persona/Soul blocks + medium_term
       history = 已完成的完整 Q/A
       human = question + StepsBlock + suffix
  -> LLMHandle.stream_generate_messages()
  -> parse_llm_output()
       strict XML -> lenient -> in-context retry -> repair LLM -> degraded finish
  -> finish: add_turn + build_static + FinishEvent
     tool: optional RiskGate -> ActionExecutor -> Step -> 下一轮
```

首步调用 `MemoryProcessor.recall()`，后续步骤固定复用同一份 medium-term，只追加当前轮
Step。历史 Q/A 来自 `PromptManager._history`，与 medium-term 摘要是两条不同数据源。

## 完成与持久化

`stream()` 在发出 `FinishEvent` 前同步执行 `manager.add_turn()` 和 `build_static()`，并保存
`_PendingFinish`。调用方随后执行 `post_process()`：

1. `MemoryProcessor.commit()` 将本轮 Q/A 写入 `medium_term.jsonl`；
2. `TimelineService` 写 conversation 事件；
3. 启用 trace 时写推理轨迹。

Persona 自动演化已从轮末断开。长期 Soul 记忆也不由 `MemoryProcessor` 被动写入；Soul
对话/Life I/O 有自己的记录链。Tao 侧可用的主动记忆工具来自
`agent.adapters.soul_tao.tools.register_soul_tools()`，实际名称包括
`soul_memory_search`、`soul_life_chronicle`，不是旧文档中的统一 `memory_recall` API。

## RiskGate 的真实覆盖

TaoLoop 只有收到非空 `risk_gate` 时才做工具级审批。仓库中 `RiskGate.from_config()` 的
常规构造点只有两个 factory：

- `agent.react.factory.build_conv_loop()`；
- `worker.react.factory.build_conv_loop()`。

因此 legacy WebUI factory ConvLoop 有工具级 approval；直接构建 TaoLoop 的 CLI、
`SubAgentRunner`、Scheduler TaskRunner、Flow Executor 默认没有。approval 发生在
TaoLoop 已接管后、工具执行前，和 WorkerWorkService 的任务级 work confirmation 无关。

## 配置与 API

`TaoConfig` 的主要字段是 `max_steps`、`storage`、`prompt`、`memory`、`persona`、
`knowledge`、`trace`、`repair_llm`、`scheduler`、`agent`、`flow`、`db`。当前 factory
仍可按 `enable_kb` 传入 knowledge 配置；不要把它描述成已删除字段。

`ConvLoop` 公开转发 `stream`、`abort`、`resolve_approval`、`restore`、`reset`、
`post_process`、`close`，并通过 `tao_loop` 暴露底层 TaoLoop。

## 相关文档

- [action/README.md](./action/README.md)
- [context/README.md](./context/README.md)
- [prompt/README.md](./prompt/README.md)
- [../session/README.md](../session/README.md)
- [../../worker/README.md](../../worker/README.md)
