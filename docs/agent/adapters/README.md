# agent/adapters

该目录连接 Agent/Soul 领域对象与 WebUI、会话队列、通知和 Tao/Soul 边界。不要把它概括为
所有 WebUI 都进入 ConvLoop：当前主 WebUI 对话走 Soul/Speak，ReAct 路由是 legacy。

## 主要入口

- `fastapi_react.py`：`/api/react/*`、`/ws/react/run`；legacy ReAct 初始化、恢复、
  reset、abort、工具查询和流式事件。
- `react_bridge.py`：`do_react_init()` 调用 `agent.react.factory.build_conv_loop()`，
  建立 legacy `SessionManager` 会话和 Flow event sink。
- `react_stream.py` / `react_wire.py` / `react_schemas.py`：Tao/SubAgent/Flow 事件到
  HTTP/WebSocket payload 的转换。
- `webui_bridge.py`：查询 legacy ReAct readiness/session，并把用户轮次桥接到 response
  queue。
- `soul_bootstrap.py`：WebUI 的 Soul-first 启动链。
- `soul_tao/`、`soul_dialogue.py`：Tao 与 Soul 工具、persona block、轮次记账的适配。

## WebUI 主对话

`src/webui/routers/speak.py` 的 `/ws/speak/run` 直接调用 `SoulService.speak_*` /
`SpeakService`。普通输入不会调用 `do_react_init()`、`SessionManager`、`ConvLoop` 或
`TaoLoop`。

路由在 Speak 前调用 `WorkerWorkService.maybe_signal()`：

```text
无任务意图 -> Speak
疑似任务 -> work_confirmation_required
  拒绝/超时 -> work_fallback_to_speak -> Speak
  同意 -> WorkerAdapter -> worker.runner -> worker.react.TaoLoop
```

这是任务级 work confirmation。legacy `/ws/react/run` 的 `approval_response` 则是
factory ConvLoop 内 RiskGate 对单个工具调用的审批，两者消息类型、时机和作用域都不同。

## legacy ReAct

`POST /api/react/init` 和 `/api/react/reinit` 返回 `deprecated: true`。
初始化后：

- HTTP fallback `/api/react/run` 提交 `TaoRequest` 并返回 SSE；
- `/ws/react/run` 同时转发 Tao 主流、SubAgent 事件和 Flow 事件；
- Flow 仍沿用部分 `plan_*` payload，并镜像 `flow_id`/`plan_id`；
- `SessionManager` 负责同会话 FIFO 与 post-process。

## 其他调用者

- CLI 在 `src/run.py` 直接构造 `agent.react.TaoLoop`，不经过这些 FastAPI 适配器；
- Scheduler 由 `AgentService`/`SchedulerEngine`/`TaskRunner` 调用 SubAgent runner；
- Bot 和主动消息通过专用 adapter/delivery hub 进入 Speak 出站链；
- Worker Work、Worker State 和 Worker Flow 的实现入口在 `src/worker/`。
