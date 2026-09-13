# agent 运行时边界

`src/agent/` 承载 Soul/Speak 主对话、会话首轮入站路由、legacy ReAct 接口、会话适配和兼容的 Agent Flow 实现。真实任务执行域位于 `src/worker/`，见 [worker/README.md](../worker/README.md)。

## 主路径

```text
WebUI /ws/agent/run
  -> agent.inbound.InboundRouter   # 仅会话首轮
       speak -> SoulService.speak_run_turn
       work  -> WorkerWorkService.submit_intent
  -> SpeakService / SpeakPipelineRouter
  -> request_driven（默认）| rhythm
  -> Speak LLM + Speak 自己的 Prompt、Memory、Session
```

**Soul/Speak 主对话不调用 `TaoLoop`，也不经过 `ConvLoop`。** `SpeakService` 在
`src/agent/soul/speak/service.py` 中自行组装上下文并调用 `SpeakLLMEngine`。分类在
`src/agent/inbound/`，由 `src/webui/routers/agent.py` 调用；`/ws/speak/run` 不参与分类。
`SoulService.speak_turn()` 已转到 `speak_run_turn()`。`legacy_qa` 仍存在于
`SpeakPipelineRouter` 的内部 runner 表和类型声明中，但 `normalize_speak_pipeline()`
不接受该值，因此不是可公开选择的主路径。详见 [inbound/README.md](./inbound/README.md)。

## ReAct 的实际入口

- CLI：`python src/run.py --mode cli` 直接构建 `agent.react.TaoLoop`，随后调用 `tao.run()`；不使用 `ConvLoop`、`SessionManager` 或 WebSocket approval 回传。
- legacy WebUI：`POST /api/react/init` 调用 `agent.react.factory.build_conv_loop()`，注册到 `SessionManager`；`/ws/react/run` 与 `/api/react/run` 再提交 `TaoRequest`。该通道已标记 deprecated。
- Scheduler：`AgentService` 持有 `SchedulerEngine` 和 `agent.soul.heartbeat.task_runner.TaskRunner`。定时任务是时钟触发；Soul 心跳由 `SoulService` 独立驱动，不经 `SchedulerEngine`。
- SubAgent：`delegate_task` 同步调用 `SubAgentRunner.run_sync()`，创建独立 TaoLoop；`TaoConfig.scheduler=None`，但调用方可显式注入共享 scheduler engine。
- Flow：TaoLoop 配置 `flow` 后注入 `run_flow`、`flow_status`、`flow_wait`、`flow_skip`。`run_flow` 在后台线程创建事件循环并调用 cluster `FlowOrchestrator.run()`。

## `agent/react` 与 `worker/react`

- `agent/react`：CLI、legacy WebUI、AgentService/Scheduler 兼容链使用的 ReAct 实现；其状态面向对话历史和 Soul。
- `worker/react`：确认后的工作、Worker SubAgent、Worker Flow 节点执行使用的实现；额外接入 `AgentStateService`，在 Prompt 中注入 Worker 画像、反思画像、记忆画像和本轮任务图，并在轮后提交反思。
- 两棵源码目前高度相似，但不是同一运行入口，不应把 `agent/react` 文档当成 Worker 的实际导入路径。

## SubAgent profile

`agent/profile.py` 与 `worker/profile.py` 当前均定义：

- `minimal`：`executor` 工具包，10 步。
- `executor`：`executor` 工具包，15 步。
- `researcher`：`researcher` 工具包，15 步。
- `researcher_with_memory`：`researcher` 工具包，追加 `soul_memory_search`、`soul_life_chronicle`，15 步。
- `analyst`：`analyst` 工具包，12 步。
- `coder`：`code` 工具包，15 步。

`SubAgentProfile` 的真实字段是 `max_steps`、`memory`、`tool_package`、`tools`、
`system_note`。这里存在关键权限差异：

- `worker.runner.SubAgentRunner` 展开 `tool_package` / `tools` 后，将
  `allowed_actions` 传给 `build_executor()`，限制 ToolManager 初始构建的工具；
- `agent.runner.SubAgentRunner` 只用解析结果过滤 Prompt 中展示的工具描述，却先通过
  无参数 `build_executor()` 注册全量 registry，未限制实际 executor。

因此 agent profile 的工具包目前只是模型可见性/引导边界，不是强制权限边界；
worker profile 虽限制初始集合，也不是完整沙箱或最终权限边界：TaoLoop 后续调用
`register_instance()` 注入 Soul、scratchpad、sandbox、scheduler、通知、SubAgent、Flow
等实例工具时，`ActionExecutor` 会自动把新工具加入已有 allow-list。`tools=None` 的语义
不能脱离具体 runner 和后续注入链统一解释。

## 确认边界

- 会话首轮分类：`agent.inbound` 判定 speak/work；击穿是用户指出该标签错误。
- 任务级 work confirmation：`WorkerWorkService` 在启动 Worker 之前发出
  `work_confirmation_required`；同意后才从 `pending_confirmation` 转为
  `starting/running`，拒绝或超时回落 Speak。这是执行授权，不是分类。
- 工具级 approval：`RiskGate` 在 TaoLoop 已开始推理后，对单个工具调用发出
  `ApprovalRequestEvent`。它不是任务接管确认。
- 当前 `RiskGate` 只在 `agent.react.factory.build_conv_loop()` 与
  `worker.react.factory.build_conv_loop()` 中构造；直接创建 TaoLoop 的 CLI、
  `SubAgentRunner`、Scheduler TaskRunner 和 Flow executor 默认没有该门控。

## 子文档

- [inbound/README.md](./inbound/README.md)
- [react/README.md](./react/README.md)
- [session/README.md](./session/README.md)
- [adapters/README.md](./adapters/README.md)
- [flow/README.md](./flow/README.md)
- [worker/README.md](../worker/README.md)
