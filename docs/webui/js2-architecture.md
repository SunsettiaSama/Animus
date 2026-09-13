# js2 — WebUI 前端分层架构

> 实现代码位于 `src/webui/static/js2/`，本文档是其分层规则与迁移对照。

js2 是前端重构后的唯一实现（旧 `js/` 在切流验收后删除）。原生 ES Module，无构建步骤，FastAPI 直接 serve。

## 分层

```
L0 protocol/   纯协议层。零依赖（不 import 本目录其他层的任何文件）。
               包含：端点注册表、出站帧构造器、入站帧解析、Speak 字段契约。
L1 transport/  网络传输层。只允许 import protocol。
               包含：HTTP 封装 + SSE 助手、WS 连接生命周期、Agent 会话通道。
L2 store/      领域状态层。允许 import protocol / transport。
               subscribe 模式的单一事实来源；UI 只读 store、只对 store 事件做渲染。
L3 features/   功能控制器。允许 import L0–L2。
               编排业务动作（发送回合、确认工作流、ack 主动消息…），持有领域意图，
               向 bus 发射事件供 UI 订阅。
L4 ui/         视图层。允许 import 任何下层，但禁止直接 fetch/WebSocket ——
               一切网络经由 features 或 transport；组件只读 store/bus 并发射用户意图。
```

依赖规则：**上层可 import 下层，禁止反向**。同层之间通过参数传递或 bus 通信，
不互相 import（例外：ui/chat 内部子模块、settings_ui/tabs 内部允许互引）。

## 并发约定（多连接 / 多窗口）

- **无全局单例连接**：`transport/agent_channel.js` 的 `AgentChannel` 是实例级会话通道；
  gen_id、session_id、重连 epoch 全部挂在实例上。将来开第二个会话就是 new 一个实例。
- `store/session_store.js` 按 channel_id 键控保存活跃通道引用，`store` 层不含任何
  WebSocket 引用以外的可变单例状态。
- 协议帧中 `gen_id` 是流代际令牌（一次只能有一个流在进行）、`session_id` 是会话身份
  （粘性路由键）、`channel_id` 是浏览器通道身份（hub 投递匹配键）。三者的构造与过滤
  只发生在 protocol + agent_channel 内，业务代码不得手工拼帧。

## 各层职责细则

| 目录 | 文件 | 职责 |
|---|---|---|
| protocol | http_api.js | 唯一端点注册表。全站禁止硬编码 `/api/*`、`/ws/*` 字符串 |
| protocol | frames.js | 出站帧构造器（session_open/user_message/work_* 等），纯函数 |
| protocol | agent_events.js | 入站帧解析 → 类型化事件：proactive 元数据提取、work_* 识别 |
| protocol | speak_fields.js | Speak 渲染字段契约（迁移自 speak_render_protocol.js） |
| transport | http.js | REST get/post/patch/del/upload + SSE 助手（统一错误与重试） |
| transport | ws_session.js | WS 连接生命周期：epoch 计数、断线重连、typing pulse 定时器 |
| transport | agent_channel.js | AgentChannel：消费 agent_events 分发为回调/总线事件；turn waiter 队列 |
| store | bus.js | 全站唯一事件总线（废除 window CustomEvent 与 setCallbacks 三轨并存） |
| store | 其余 | session / chat / work / history 四个领域 store |
| features | conversation.js | 发送管线、turn 编排、route_decision/route_pierce 处理 |
| features | work_confirmation.js | 工作确认流编排（批准/拒绝/中止/监控） |
| features | proactive.js | 主动消息 dedup / ack / 未读点 |
| ui | chat/* | render 拆分：markdown、气泡、ReAct 步骤、Speak 流式、打字态 |

## 禁止事项

1. UI/feature 文件出现字面量端点字符串（一律从 protocol/http_api.js 取）。
2. 通过 `window.dispatchEvent(CustomEvent)` 跨模块通信（统一走 bus）。
3. store 直接操作 DOM；ui 组件直接发网络请求。
4. 前端解析 character 原始标签字符串（后端已拆字段事件，见 speak_fields.js 头注释）。

## 迁移对照

旧文件 → 新位置：
- api.js → protocol/http_api.js（PATHS）+ transport/http.js（http/wsFactory/poll）
- streaming.js → transport/ws_session.js + transport/agent_channel.js
- speak_render_protocol.js → protocol/speak_fields.js
- work/store.js → store/work_store.js
- state.js → store/session_store.js（全局 S 废除）
- history.js → store/history_store.js（数据）+ ui/screens/history_list.js（渲染）
- render.js → ui/chat/{markdown,bubbles,speak_stream,typing}.js
  （ReAct 步骤渲染仅服务 legacy /ws/react/run，未迁移）
- workspace.js → features/conversation.js（编排）+ ui/screens/workspace.js（视图契约实现）
- modules/{llm,memory,persona,soul,react,voice,bot,infra}.js → features/basics.js 门面
- settings/ → ui/settings_ui/{modal,tabs/}（端点改走 protocol/http_api.js）
- modules/{plan,scheduler,benchmark}.js → features/{plan,scheduler,bench}_bridge.js
  （整体移植，私有端点表合并进 http_api.js）

## 实现备注（与最初设想的偏离）

- 入口拆成 app.js（动态导入加载器 + 启动失败可视面板 + #probe= 诊断装置）
  与 app_main.js（真实装配）。动态导入晚于 DOMContentLoaded 到达时依然
  保证 boot 恰好执行一次（readyState 双向判断）。
- features/basics.js 是设置 tabs 与工作站卡片共用的配置域数据门面，
  避免八个单文件小模块碎片区。
- 三大屏以 bridge 形式整体移植，内部 DOM/SSE 逻辑未拆，后续单独重构。
- 旧 `js/` 目录已删除；`static/dist/`（遗留 Vue 产物）暂保留待议。
- 已知未逐项实测路径：route_pierce 纠错卡、work 确认卡（需要真实的
  work 分类消息触发）、主动消息 SSE 推送。协议路径均有单测式冒烟
  （Node 侧 frames/classify 断言）。
