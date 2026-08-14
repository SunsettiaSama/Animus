# agent/session

`src/agent/session/` 是 legacy ReAct 的队列化会话层，不是 Soul/Speak 的会话实现。

## 类型与并发

- `SessionManager`：`session_id -> AgentSession` 注册表，提供 `create_session`、
  `register`、`get`、`destroy`、`submit`、`stop_all`。
- `AgentSession`：持有一个 `ConvLoop` 和专属 daemon worker thread。
- `TaoRequest`：请求信封，含 `kind`、`session_id`、`question`、`payload`、`gen_id`、
  `stream_mode`。

同一 `AgentSession` 通过 FIFO queue 串行执行；不同 session 各有线程，可并发。当前
`AgentSession` 实际只处理 `kind="user"`，`heartbeat` 和 `soul_tick` 仍是预留值。

## legacy WebUI 调用

```text
POST /api/react/init
  -> do_react_init()
  -> build_conv_loop()
  -> SessionManager.create_session("webui", conv_loop)

/ws/react/run 或 /api/react/run
  -> SessionManager.submit(TaoRequest)
  -> AgentSession._handle_user()
  -> ConvLoop.stream()
  -> react_stream composer -> response queue
  -> ConvLoop.post_process()
```

WebSocket 上行的 `approval_response` 通过 `AgentSession.resolve_approval()` 转发给
ConvLoop/TaoLoop。abort 会设置 TaoLoop stop event；未完成轮次随后 rollback。

## 不属于该模块的会话

- `/ws/speak/run` 使用 `SpeakSessionManager` / `SpeakSessionService` 和 Speak 自己的输入、
  推送、typing、interrupt、生命周期队列，不注册到这里；
- `WorkerWorkService` 按 `work_id` 管理确认、运行、监控和终态，不是 `AgentSession`；
- Scheduler 使用自己的 task store/clock，Soul heartbeat 也不提交 `TaoRequest`。
