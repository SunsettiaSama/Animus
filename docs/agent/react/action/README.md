# agent/react/action

动作层负责工具注册、Pydantic 参数校验、执行、Skill/MCP 接入，以及可选的工具级风险审批。
`src/agent/react/action/` 与 `src/worker/react/action/` 结构相近；Worker 执行链应导入后者。

## 核心组件

- `BaseAction`：声明 `name`、`description`、`args_model` 和 `execute()`。
- `ActionExecutor`：注册 class/instance/LangChain tool，校验 JSON 参数，支持单次和并行调用。
- `ToolRegistry`：保存工具元数据和 `ToolPackage`。
- `ToolManager`：构建 executor、解析工具包、生成 Prompt 描述，并挂载 Skill/MCP registry。
- `ToolSearchAction`：元工具。默认主工具描述会展示它，executor 也会注册它。

默认展示的主工具是 `calculator`、`get_datetime`、`web_search`、`unit_converter`、
`word_count`，并附 `tool_search`。registry 还包含文本、数据、文件、HTTP、Python、
知识库、scheduler 等工具；是否能实际运行还取决于 TaoLoop 是否注入 sandbox、
KnowledgeBase、SchedulerEngine、Soul 或通信服务。

## 工具包

`ToolManager.resolve_tools()` 可展开当前内置包：

- `planner`：草稿本、搜索、网页抓取、知识检索；
- `executor`：通用计算/搜索/文本/草稿本和只读文件；
- `researcher`：搜索、HTTP、知识库读写、文件读写；
- `analyst`：计算、Python、数据处理和文件 I/O；
- `code`：Python、文件系统、网络下载和数据处理；
- `filesystem`、`knowledge`、`network`、`full`。

`SubAgentProfile.tool_package` 与 `tools` 在两套 runner 中的强制性不同：

- `worker.runner.SubAgentRunner` 展开工具包和追加项，将 `allowed_actions` 传给
  `ToolManager.build_executor()`，由 `ActionExecutor.restrict_to()` 限制
  ToolManager 初始注册的工具；
- `agent.runner.SubAgentRunner` 先无参数调用 `build_executor()` 注册全量 registry，随后
  只用 profile 的解析结果生成 Prompt 工具描述，没有限制 executor。

所以 agent SubAgent 的 profile 当前只减少模型看到的工具，不构成可靠 allow-list；
worker SubAgent 的 profile 会限制初始工具集合，但仍不是完整沙箱或最终权限边界。
`ActionExecutor.register_instance()` 在 allow-list 已存在时会自动把新实例名加入
`_allowed_actions`；TaoLoop 后续注入的 Soul、scratchpad、sandbox、scheduler、通知、
`delegate_task`、`flow_*` 等实例工具因此可以扩展可执行集合。不能用一条统一的
“`tools=None`”规则描述二者，也不能把 worker profile 当成不可扩展的安全策略。

## TaoLoop 动态注入

- scratchpad：`note_write`、`note_read`、`note_delete`；
- sandbox 可用时：`file_*`、`http_request`、`python_run`；
- knowledge 配置非空时：`knowledge_*` 及研究/报告 Skill；
- Soul 可用时：由 `agent.adapters.soul_tao.tools` 注入 `soul_*` 工具；
- SchedulerEngine 可用时：`scheduler_add`、`scheduler_list`、`scheduler_cancel`、
  `timeline_read`；
- `notify_fn` / 通信配置可用时：通知与 bot 工具；
- `TaoConfig.agent` 非空时：`delegate_task`；
- `TaoConfig.flow` 非空时：`run_flow`、`flow_status`、`flow_wait`、`flow_skip`。

## SubAgent 与 Flow

`delegate_task(instruction, profile)` 是同步 Skill。agent Tao 使用
`agent.runner.SubAgentRunner`，worker Tao 使用 `worker.runner.SubAgentRunner`；子 TaoLoop
完成后 answer 才回到父步骤。当前 profile 包括 `minimal`、`executor`、`researcher`、
`researcher_with_memory`、`analyst`、`coder`，但 Skill 参数说明尚未列出 `coder`。

`run_flow(question)` 在后台线程创建 asyncio event loop 并调用 cluster
`FlowOrchestrator.run()`，立即返回当前 flow/plan id；其余三个 `flow_*` Skill负责查询、
等待和跳过任务。`flow_id` 是对历史 `plan_id` 的别名。旧 `plan_tools.py` 不是 TaoLoop
当前默认注入路径。

## RiskGate

RiskGate 的解析顺序是 allow-list 强制级别、assessor 评估、与
`auto_approve_level` 比较。超过阈值时 TaoLoop 发出 `ApprovalRequestEvent`，等待
`resolve_approval(request_id, approved)`；并行工具批次会先收集所有审批，任一拒绝或超时
则取消整批。

覆盖范围必须按装配点理解：

- `agent.react.factory.build_conv_loop()` 和 `worker.react.factory.build_conv_loop()` 使用
  `RiskGate.from_config(RiskConfig())`；
- CLI `_build_tao()`、`SubAgentRunner`、Scheduler TaskRunner、Flow executor 都直接构造
  TaoLoop，默认未传 RiskGate；
- legacy `/ws/react/run` 实现了 `approval_response` 回传；Speak/Worker 的
  `work_confirmation_response` 是另一条任务级确认协议。

因此 RiskGate 不是全局安全边界，也不覆盖所有 Tool/Skill/MCP 调用。

## 调用格式

ActionExecutor 接收：

```json
{"action": "calculator", "args": {"expression": "1+1"}}
```

TaoLoop 新输出格式允许 `<A>` 中包含调用数组并并行执行；执行结果会写回当前轮
`Step`，下一步通过 `StepsBlock` 进入 Prompt。
