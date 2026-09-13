# worker

`src/worker/` 是真实任务执行域：接收经用户确认的工作，运行受 profile 限制的 ReAct
Worker，并维护任务状态、跨轮画像和 DAG Flow。它不负责 Soul/Speak 的日常对话与人格表达。

## 与 agent 的边界

- `agent/inbound`：会话首轮 Speak/Worker 分类。WebUI `/ws/agent/run` 在这里判定。
- `agent/soul/speak`：主对话。分类为 speak 后进入这里，不走 TaoLoop。
- `agent/react`：CLI 与 legacy `/api/react/*`、`/ws/react/run` 的 ReAct 实现。
- `worker/react`：确认后的 Worker、Worker SubAgent、Worker Flow 节点使用的 ReAct 实现。
- `worker/work`：执行确认与生命周期门面，不再用正则 matcher 做主判定。
- `worker/state`：Worker 专属 AgentState，不是 Soul persona，也不是 ReAct
  `MemoryProcessor`。
- `worker/flow`：Worker 的 base/cluster Flow 轨道。

## WorkerWorkService 确认链

```text
/ws/agent/run 首轮 user_message
  -> agent.inbound.InboundRouter.handle
  -> WorkIntentSignal(reason=agent_inbound_*)
  -> WorkerWorkService.submit_intent()
       pending_confirmation -> work_confirmation_required
  -> work_confirmation_response
       reject/timeout -> declined -> fallback Speak
       approve -> starting -> daemon worker thread -> running
  -> WorkerAdapter(profile="executor")
  -> worker.runner.SubAgentRunner
  -> worker.react.TaoLoop
  -> finished | failed | aborted
```

`WorkerWorkService` 维护 `work_id -> WorkRecord`、合法状态迁移、60 秒默认确认超时、会话
event sink、进度快照和 abort。未经 `pending_confirmation -> starting` 转换不会启动 Worker。
`reason` 以 `agent_inbound` 开头的信号跳过短文本/闲聊二次分类，只做执行确认。
非 inbound 信号仍可被轻量判定直接拒绝并回落 Speak。

这层确认决定“是否把整项工作交给 Worker”，是任务级 confirmation。它不同于 TaoLoop
RiskGate 的工具级 approval：后者只在已运行的 ReAct 中审批某个工具调用。

## Worker 执行

`WorkerAdapter.run_single_task()` 使用 `worker.profile.SubAgentConfig` 选择 profile，
再调用 `worker.runner.SubAgentRunner.run_sync()`。runner：

1. 展开 `tool_package`，并合并显式 `tools`；
2. 用 `allowed_actions` 限制 ActionExecutor；
3. 创建 `worker.react.TaoLoop`，配置 `scheduler=None`；
4. 流式收集 Step/Finish，提交 post-process；
5. 返回 `answer`、`step_count`、`steps`、`steps_log`。

内置 profile：`minimal`、`executor`、`researcher`、`researcher_with_memory`、`analyst`、
`coder`。对应工具包定义在 `worker/react/action/manager.py`。

## AgentState

`AgentStateService` 持久化三个 slot：

- `worker_portrait`：稳定任务身份与交付原则；
- `reflection_portrait`：依据已完成 Worker 轨迹更新的跨轮反思；
- `memory_portrait`：从 Soul memory、medium-term、persona revision、stable anchor 等来源
  蒸馏的长期工作记忆画像。

每轮 Worker Tao：

```text
begin_turn(question)
  -> immutable AgentStateSnapshot + TurnTaskGraph
  -> 三个 portrait 作为 system MemoryBlock
  -> task graph 追加到 system
工具执行/finish
  -> task graph 记录动作、结果和终态
post_process
  -> submit_reflection(question, answer, steps, task_graph, terminal_status)
  -> WorkReflectionSidecar
WorkerWorkService 收尾
  -> submit_refresh_fallback()
  -> MemoryDistillChain: read -> gather -> revision check -> derive -> commit
```

`memory_distill` 与 `work_reflection` 是并行 sidecar。`StateDerivationChain` 在 source 为空或
revision 未变时不调用 LLM、不写盘。Worker Tao 每个请求都重建 static prompt，确保新反思
下一轮可见。

## Flow

Worker Flow 有两层：

- `worker/flow/base`：manifest/node 级通用 DAG 原语，支持 atomic/flat/nested 展开、
  registry executor/verifier、预算和 replanner；
- `worker/flow/cluster`：当前 PlanDocument 编排运行时，含 Planner/Executor/Replanner、
  并行依赖调度、snapshot/log、人类 patch 和 SSE 事件。

cluster Executor 会把原始目标、当前 task 和依赖节点结果组成指令，再调用
`worker.runner.SubAgentRunner`；`AgentStateService` 会继续传到节点 TaoLoop。

当前 `worker/flow/__init__.py` 的主要公开 `FlowOrchestrator` 来自 cluster，同时仍从
`agent.flow.base` / `agent.flow.manager` 引出部分 base 和前端桥接符号。这说明双轨尚未
完全物理收敛，文档和调用代码应写明具体导入路径。

## RiskGate 覆盖

`worker.react.factory.build_conv_loop()` 会创建 RiskGate，但 `WorkerWorkService` 的实际链是
`WorkerAdapter -> SubAgentRunner -> TaoLoop`，runner 没有传 `risk_gate`。Worker Flow
executor 同样经 SubAgentRunner。因此任务确认后的这些默认 Worker 路径没有自动获得工具级
approval；不能把任务级 confirmation 当成 RiskGate 的替代描述，也不能声称 RiskGate
全局覆盖 Worker。
