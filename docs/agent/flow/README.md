# Flow

Flow 用于复杂目标的 DAG 规划、并行执行和重规划。当前源码存在 base 与 cluster 双轨，
并同时保留 `agent.flow` 和 `worker.flow` 两套路径；必须按调用者说明具体实现。

## 双轨

### base

`agent/flow/base` 与 `worker/flow/base` 定义 manifest/node 级编排原语：

- `ManifestPlanSpec` 是声明源，`DagGraphManager` 是运行状态源；
- `DagOrchestrator` 执行 bootstrap、依赖调度、atomic/flat/nested 展开；
- `AtomicPlanner` 判定节点粒度；
- `NodeRegistry` 构造 executor/verifier；
- `BaseReplanner` 在失败或完成事件上修改 spec，再同步 graph。

base 适合可复用的节点运行时和递归分解，不是 WebUI 当前 `PlanDocument` API 的同义词。

### cluster

`agent/flow/cluster` 与 `worker/flow/cluster` 是 PlanDocument/PlanTask 运行时：

```text
PlannerAgent -> PlanDocument
  -> FlowOrchestrator._dispatch_all()
  -> ExecutorAgent -> SubAgentRunner -> TaoLoop
  -> SnapshotStore / PlanLogger / event subscribers
  -> ReplannerAgent / HumanPatch
  -> PlanResult
```

两套 cluster 都提供 lifecycle、当前 plan id、任务进度、running tasks、snapshot、
human edit 和 SSE 事件；但节点指令的数据注入并不相同。`PlanOrchestrator` 是
`FlowOrchestrator` 的别名。

## 调用路径

- legacy agent Tao：`agent.react.TaoLoop` 在 `TaoConfig.flow` 非空时创建
  `agent.flow.cluster.FlowOrchestrator` 并注入四个 `flow_*` Skill。
- Worker Tao：`worker.react.TaoLoop` 创建
  `worker.flow.cluster.FlowOrchestrator`，并把 `AgentStateService` 传到 Flow executor。
- `run_flow(question)`：后台线程中创建 asyncio loop，调用 cluster
  `orchestrator.run(question)`。
- `flow_status()`：读取 lifecycle、progress、running/pending/done/failed task。
- `flow_wait(timeout_seconds)`：等待当前后台 run state。
- `flow_skip(task_id, cascade)`：在当前 PlanDocument 标记跳过。
- legacy WebUI：Flow 事件由 TaoLoop sink 经 `react_bridge` 扇出到 `/ws/react/run`；
  `/api/plan/*` 仍使用历史 plan 命名。

`flow_id` 和 `plan_id` 当前指同一标识，桥接层会镜像两个字段。

## SubAgent 与数据流

- `worker.flow.cluster.ExecutorAgent` 调用 `build_task_instruction(task, doc)`，把原始
  objective、当前 task、已完成依赖节点的 result 和输出约束组装后交给
  `worker.runner.SubAgentRunner`。
- `agent.flow.cluster.ExecutorAgent` 没有 `build_task_instruction()`；它把 orchestrator
  传入的 `task.description` 原样转给 `agent.runner.SubAgentRunner`，不会自动附加 objective
  或依赖结果。

两者都会按 `PlanTask.profile` / `params.profile` 选择 profile，并可按 task
`max_steps` 覆盖步数。只有 Worker cluster 继续传递 AgentStateService，使节点 TaoLoop
获得 Worker 画像/任务图链。两条 Flow 都不进入 Soul/Speak 主对话 TaoLoop。

## 与其他编排方式的区别

- Scheduler：按时间触发任务，入口是 `SchedulerEngine`；不是 DAG。
- `delegate_task`：父 TaoLoop 同步等待一个 SubAgent；不是后台 Flow。
- WorkerWorkService：决定整项任务是否接管并管理 work 状态；确认后可以运行单 Worker，
  当前不等同于自动选择 Flow。
- Soul/Speak：主对话编排和 director pipeline；不调用 Flow/TaoLoop，除非用户明确确认后
  进入 Worker 或 legacy ReAct 主动调用 `run_flow`。

## 风险与确认

Flow executor 通过 SubAgentRunner 直接创建 TaoLoop，默认不传 RiskGate。只有使用
`agent.react.factory.build_conv_loop()` 或 `worker.react.factory.build_conv_loop()` 创建
的外层 ConvLoop 获得工具级 RiskGate；这不会自动传播到 Flow 节点。

WorkerWorkService 的 `work_confirmation_required` 是 Flow/Worker 启动前的任务级确认，
RiskGate 的 `ApprovalRequestEvent` 是 TaoLoop 内工具执行前的工具级审批，二者不可混用。

## 当前导出边界

`worker/flow/__init__.py` 的 cluster 类型来自 `worker.flow.cluster`，但部分 base component、
frontend bridge 和 streaming helper 仍从 `agent.flow` 导出；`worker.flow.cluster` 内也仍有
若干 `agent.flow.base` import。双轨是当前真实状态，不应写成已完全迁移或已统一。
