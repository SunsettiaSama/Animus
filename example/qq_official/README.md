# QQ 官方机器人接入

通过腾讯 **QQ 开放平台** 官方 API 将 ReAct Agent 接入 QQ，
无需安装 NapCat / Lagrange 等任何外部进程，纯 Python 运行。

## 架构

```
QQ 用户
    │ 私聊 / @机器人（群）
    ▼
腾讯 QQ 官方 WebSocket Gateway
    │ botpy SDK（qq-botpy）
    ▼
QQOfficialTransport.on_event(raw)
    │ OneBot 11 格式
    ▼
BotService → AgentSession → TaoLoop
    │ reply
    ▼
botpy api.post_c2c_message / post_group_message
    │
    ▼
QQ 用户收到回复
```

---

## 前提：在 QQ 开放平台注册机器人

1. 打开 <https://q.qq.com/>，登录后进入 **QQ 开放平台**
2. 创建应用 → 选择 **机器人**
3. 获取：
   - **AppID**（数字串）
   - **AppSecret**（字符串）
4. 配置 **发布环境**：
   - 开发阶段使用 **沙箱环境**（is_sandbox: true），只有开发者可以测试
   - 上线后切换到正式环境（is_sandbox: false）
5. 在 **权限管理** 中申请以下权限：
   - `发送消息到私信` / `发送消息到群`（根据需要）

---

## 第一步：安装 SDK

```bash
pip install qq-botpy
```

---

## 第二步：配置 bot_config.yaml

编辑 `config/infra/bot_config.yaml`：

```yaml
transport: qq_official

# QQ 开放平台 → 机器人管理 → AppID 和 AppSecret
appid:  "你的AppID"
secret: "你的AppSecret"

# 沙箱模式（开发测试时开启，正式上线改为 false）
is_sandbox: false

# 访问控制（留空 = 不限制）
allowed_private_users: []   # 仅响应指定用户（openid 哈希整数，通常留空）
allowed_groups:        []   # 仅响应指定群（openid 哈希整数，通常留空）
command_prefix:        ""   # 触发前缀，群消息已自动去除 @机器人 前缀

max_sessions:     100
session_ttl_hours: 24
```

> **注意**：`allowed_private_users` / `allowed_groups` 中填入的整数
> 是 openid 的 MD5 哈希值（由 `QQOfficialTransport._openid_to_id()` 生成），
> 不是真实 QQ 号。通常保持为空（不限制）即可。

---

## 第三步：启动 ReAct 服务

```powershell
cd G:\ReAct
python main.py webui
```

- WebUI 地址：`http://127.0.0.1:8000`
- 在 WebUI 中完成 LLM 配置
- LLM 初始化后，BotService 自动连接 QQ 官方 Gateway

日志示例：

```
[webui] LLM auto-loaded  model='qwen3-0.6b'
[QQOfficialTransport] connected, appid=12345678
INFO  BotService  new session private_98765432100001
```

---

## 第四步：测试

| 场景 | 触发方式 |
|---|---|
| 私聊 | 在 QQ 中直接私信机器人账号 |
| 群聊 | 在已添加机器人的群中 @机器人 发消息 |

---

## 官方 API 限制说明

| 场景 | 被动回复有效期 | 每条消息最多回复次数 |
|---|---|---|
| 群聊 | 5 分钟 | 5 次 |
| 私聊（C2C） | 60 分钟 | 5 次 |

- **被动回复**：用户先发消息，机器人在有效期内回复
- **主动推送**：每月每用户/每群仅 4 条（超出限制），通常不可用
- 机器人**不能获取真实 QQ 号**，仅有 openid

---

## 与 NapCat 方案对比

| 维度 | QQ 官方 API（本方案） | NapCat |
|---|---|---|
| 外部进程 | ❌ 不需要 | ✅ 需要安装并运行 |
| 稳定性 | ✅ 官方维护 | ⚠️ 随 QQ 更新可能失效 |
| 能力 | 群 @机器人 + 私聊 | 任意消息 + 主动发送 |
| 获取 QQ 号 | ❌ 仅有 openid | ✅ 真实 QQ 号 |
| 注册要求 | 需要开放平台账号 | 有 QQ 账号即可 |

---

## 常见问题

**Q：连接后收不到消息？**
- 确认 QQ 开放平台后台已开启对应权限（群/私聊）
- 沙箱环境下只有配置为"开发者"的账号才能触发
- 确认机器人已添加到群中（群消息需先邀请机器人入群）

**Q：回复失败，提示 `msg limit exceed`？**
- 5 分钟（群）/ 60 分钟（私聊）的被动回复窗口已过期
- Agent 处理时间过长时可能超出窗口，需优化响应速度

**Q：`secret` 和 `token` 的区别？**
- `secret` 即 QQ 开放平台的 **AppSecret**，用于 OAuth2 认证（当前方案）
- 老版 botpy 使用 `token`（Bot Token），已逐步废弃
