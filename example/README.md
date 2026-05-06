# 接入示例

本目录收录将 ReAct Agent 接入各类通信平台的示例。

## 目录结构

```
example/
├── napcat_qq/          QQ（通过 NapCat，推荐起步方式）
└── custom_transport/   自定义平台接入模板（Telegram / Discord / HTTP 等）
```

---

## 核心概念：三层结构

```
平台（QQ / Telegram / ...）
    │  原生协议
    ▼
Transport（传输层）                 ← 你只需关心这一层
    │  OneBot 11 格式事件 dict
    ▼
BotService（服务装配层）            ← 框架自动处理
    │  session_id 路由
    ▼
AgentSession → ConvLoop → TaoLoop  ← 框架自动处理
```

**你需要做的**：
- 选择现成 Transport（如 `ForwardWSTransport` 对接 NapCat）
- 或实现 `BaseTransport` 接入任意平台（见 `custom_transport/`）

**你不需要做的**：
- 不需要了解 LLM 调用细节
- 不需要管理多会话并发
- 不需要处理 Agent 内部状态

---

## 快速开始：QQ（NapCat）

最快 5 分钟内让 Bot 跑起来：

1. 安装并配置 NapCat → 见 [napcat_qq/README.md](napcat_qq/README.md)
2. 编辑 `config/infra/bot_config.yaml`，填写 `ws_url` 和访问控制规则
3. `python main.py webui`
4. 在 WebUI 中初始化 LLM
5. 向 Bot 发消息即可

---

## 会话路由规则

| 消息类型 | session_id 键 | 含义 |
|----------|--------------|------|
| 私聊 | `private_<user_id>` | 每人独立的 Agent 上下文 |
| 群聊 | `group_<group_id>` | 全群共用同一 Agent 上下文 |

群聊模式下，所有群成员的消息进入同一 `ConvLoop`，Agent 能看到完整的群聊对话历史。

---

## 关闭前端后服务是否继续？

是的。`BotService` 是基础设施层服务（`BaseServiceManager`），在 FastAPI `@startup` 时启动，
运行在 uvicorn 的 asyncio event loop 中，与浏览器是否连接完全无关。

| 操作 | 影响 |
|------|------|
| 关闭浏览器标签页 | 无影响 |
| WebUI WebSocket 断开 | 无影响 |
| 关闭 uvicorn 进程 | Bot 服务停止 |

---

## 访问控制配置速查

```yaml
# config/infra/bot_config.yaml

# 只响应指定 QQ 的私聊
allowed_private_users: [123456789]

# 只响应指定群
allowed_groups: [112233445, 556677889]

# 需要前缀才触发（如 "/" 或 "@Bot "）
command_prefix: "/"

# 不限制（全量响应）
allowed_private_users: []
allowed_groups: []
command_prefix: ""
```

---

## 监控 API

服务运行期间可通过以下接口查看状态：

```
GET  /api/bot/status    → 连接状态 + 活跃会话数
GET  /api/bot/sessions  → 所有活跃会话列表（含空闲时长）
POST /api/bot/start     → 手动启动
POST /api/bot/stop      → 手动停止
```
