# agent/adapters

把 **`ConvLoop` / `TaoLoop`** 接到传输层的适配桥：**FastAPI** 路由、WebUI 事件流、会话管理等。

源码：`src/agent/adapters/`。

---

## 文件索引

| 文件 | 用途 |
|---|---|
| `fastapi_react.py` | ReAct WebSocket / HTTP 与 Tao 流水线对接 |
| `fastapi_chat.py` | Chat 模式路由 |
| `react_stream.py` | 事件序列化与推送辅助 |
| `react_bridge.py` / `react_wire.py` / `react_schemas.py` | 请求/响应结构与桥接常量 |
| `webui_bridge.py` | WebUI 状态与 Agent 运行时 glue |

详情以实现为准；会话注册通常配合 **`agent.session.SessionManager`**。

---

## 相关文档

- [agent/session/README.md](../session/README.md)
- [webui/README.md](../../webui/README.md)
