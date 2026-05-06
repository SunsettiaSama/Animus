# NapCat QQ 接入示例

通过 NapCat 将 QQ 接入 ReAct Agent，使其能够实时响应 QQ 私聊和群聊消息。

## 架构概览

```
QQ 客户端
    │ QQ 协议
    ▼
NapCat（OneBot 11 WS 服务端，监听 :3001）
    │ WebSocket  ws://127.0.0.1:3001
    ▼
ForwardWSTransport（infra/network/bot/onebot/transport/forward_ws.py）
    │ on_event(raw_dict)
    ▼
BotService._dispatch()  →  MessageEvent
    │ session_id = "group_<id>" | "private_<uid>"
    ▼
AgentSession（per-user asyncio.Queue + ThreadPoolExecutor）
    │ ConvLoop.stream(question)
    ▼
TaoLoop（Thought → Action → Observation）
    │ LLMService  /  Tools  /  Memory
    ▼
回复文本  →  BotAPI.send_reply()  →  NapCat  →  QQ
```

关闭浏览器 / WebUI 前端之后，上述链路仍然持续运行，只要 uvicorn 进程存活即可。

---

## 第一步：安装 NapCat

> NapCat 是基于 NTQQ 的无头框架，不需要 Wine 或虚拟机。

### Windows

1. 下载最新版：<https://github.com/NapNeko/NapCatQQ/releases>
2. 解压，将 `NapCat` 目录放在任意位置（如 `C:\NapCat`）
3. 在 NTQQ 安装目录找到 `QQ.exe`（默认 `C:\Program Files\Tencent\QQNT\QQ.exe`）

### Linux（无头服务器）

```bash
# 以 Docker 方式运行（推荐）
docker run -d \
  --name napcat \
  -p 3001:3001 \
  -e ACCOUNT=你的QQ号 \
  mlikiowa/napcat-docker:latest
```

---

## 第二步：配置 NapCat WebSocket 服务

启动 NapCat 后，在 NapCat WebUI（默认 `http://127.0.0.1:6099`）中进行配置：

1. 进入 **网络配置** → **添加配置**
2. 选择 **WebSocket 服务端**
3. 填写：
   - **启用**：✅
   - **Host**：`0.0.0.0`
   - **Port**：`3001`
   - **Access Token**：留空（或填入后在 bot_config.yaml 中对应填写）
4. 保存并重启 NapCat

验证 NapCat 是否正常监听：

```powershell
# Windows
Test-NetConnection -ComputerName 127.0.0.1 -Port 3001

# Linux
ss -tlnp | grep 3001
```

---

## 第三步：配置 bot_config.yaml

编辑 `G:\ReAct\config\infra\bot_config.yaml`：

```yaml
transport: forward_ws
ws_url: "ws://127.0.0.1:3001"   # NapCat WS 地址
access_token: ""                  # 若 NapCat 设置了 token，在此填写

reconnect_interval_sec: 5        # 断线重连初始间隔（指数退避，最大 60s）

# 访问控制（留空 = 不限制）
allowed_private_users: []        # 仅响应指定 QQ 号的私聊，如: [123456789, 987654321]
allowed_groups: []               # 仅响应指定群的消息，如: [112233445]

command_prefix: ""               # 触发前缀，如 "/" 则只有 "/问题" 才响应

max_sessions: 100                # 最多并发会话数
session_ttl_hours: 24
```

### 典型配置示例

**仅私聊白名单模式**（只有你自己能用）：
```yaml
ws_url: "ws://127.0.0.1:3001"
allowed_private_users: [你的QQ号]
allowed_groups: []
```

**群聊指令模式**（群里发 `/问题` 才触发）：
```yaml
ws_url: "ws://127.0.0.1:3001"
allowed_groups: [你的群号]
command_prefix: "/"
```

**全量开放**（任意私聊 + 任意群）：
```yaml
ws_url: "ws://127.0.0.1:3001"
allowed_private_users: []
allowed_groups: []
command_prefix: ""
```

---

## 第四步：启动 ReAct 服务

```powershell
cd G:\ReAct
python main.py webui
```

服务启动后：
- WebUI 地址：`http://127.0.0.1:8000`
- 在 WebUI 中完成 LLM 配置（填写 API 地址 + 模型名）
- LLM 初始化完成后，BotService 自动连接 NapCat 开始工作

也可以通过 API 手动控制：

```bash
# 查看 bot 连接状态
curl http://127.0.0.1:8000/api/bot/status

# 查看活跃会话
curl http://127.0.0.1:8000/api/bot/sessions

# 手动启动
curl -X POST http://127.0.0.1:8000/api/bot/start

# 手动停止
curl -X POST http://127.0.0.1:8000/api/bot/stop
```

---

## 第五步：验证

向 Bot 账号发送私聊消息，或在已配置的群中发送消息，应收到 Agent 的回复。

日志输出示例：

```
[webui] LLM auto-loaded  model='qwen3-0.6b'
[webui] BotService started  url='ws://127.0.0.1:3001'
INFO  ForwardWSTransport  connected to ws://127.0.0.1:3001
INFO  BotService  new session private_123456789
```

---

## 常见问题

**Q: Bot 无响应，日志显示 `disconnected`？**
- 检查 NapCat 是否已启动并监听 3001 端口
- 确认 `ws_url` 配置正确
- 查看 NapCat 日志确认 QQ 账号登录状态

**Q: 想让 Bot 关闭 WebUI 后继续运行？**
- 直接关闭浏览器标签页即可，BotService 运行在 uvicorn 进程中，与浏览器无关
- 若要完全无 UI 运行，保持 `python main.py webui` 进程在后台即可（或用 `nohup` / `screen`）

**Q: 如何限制 Bot 只回复特定人？**
- 在 `bot_config.yaml` 的 `allowed_private_users` 填入 QQ 号列表
