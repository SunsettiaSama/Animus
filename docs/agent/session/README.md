# agent/session

多会话承载：`SessionManager` 维护 `session_id → AgentSession`，**不同会话并发**（各自 worker），**同一会话内请求 FIFO 串行**。

源码：`src/agent/session/`。

---

## 类型

| 模块 | 说明 |
|---|---|
| `SessionManager` | `create_session` / `register` / `get` / `destroy` / `submit(TaoRequest)` |
| `AgentSession` | 绑定 `ConvLoop`，队列化处理推理请求 |
| `TaoRequest` | 单次 Tao 调用载荷（含 `session_id`） |
| `ChatSession` | WebUI Chat 路径可用的轻量会话类型（可被 `register` 注册） |

---

## 典型用法

HTTP / WebSocket 适配层（见 `agent/adapters/`）解析会话 id 后 **`submit`** 到对应 `AgentSession`，由会话线程消费队列并与 `TaoLoop` / `ConvLoop` 交互。

---

## 相关文档

- [agent/adapters/README.md](../adapters/README.md)
