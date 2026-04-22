# webui

基于 FastAPI 的轻量 Web 聊天界面，支持普通对话与 ReAct 推理两种模式，在浏览器中配置、对话并查看完整 Prompt 上下文。

## 文件

| 文件 | 说明 |
|---|---|
| `app.py` | FastAPI 后端，REST API + WebSocket 流式接口 |
| `index.html` | 单页前端，纯 HTML + Vanilla JS，无框架依赖 |
| `run.py` | 启动入口 |

## 启动

```bash
cd G:\ReAct\src\webui
python run.py
```

访问 `http://localhost:8080`。

---

## API

### LLM 管理

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/config` | GET | 读取当前 LLM 配置（从 `config/llm_core/config.yaml`）|
| `/api/config/save` | POST | 保存 LLM 配置到 YAML |
| `/api/init` | POST | 初始化 / 切换 LLM |
| `/api/status` | GET | 查询 LLM 初始化状态与 ReAct 会话状态 |

### 普通对话

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/chat` | POST | SSE 流式对话（纯文本，带多轮 history）|
| `/ws/chat` | WebSocket | WebSocket 流式对话（同上）|

### ReAct 推理

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/react/init` | POST | 初始化 ReAct 会话（选择语言、工具、步数）|
| `/api/react/run` | POST | SSE 流式 ReAct 推理 |
| `/ws/react/run` | WebSocket | WebSocket 流式 ReAct 推理（主路径）|
| `/api/react/reset` | POST | 清空当前会话历史 |
| `/api/react/restore` | POST | 从保存的对话 JSON 恢复会话历史 |
| `/api/react/tools` | GET | 查询已注册工具列表（按分类）|
| `/api/react/tools/search` | GET | 语义搜索工具 |

### 对话历史

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/history` | GET | 列出所有已保存对话 |
| `/api/history/{id}` | GET | 读取单条对话 |
| `/api/history` | POST | 保存对话 |
| `/api/history/{id}` | DELETE | 删除对话 |

### 人格（Persona）

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/persona` | GET | 读取人格配置（画像 + 配置项）|
| `/api/persona/save` | POST | 保存人格配置（画像 + 是否启用 + 各项参数）|
| `/api/persona/chronicle` | GET | 读取人格事件日志 |

---

## WebSocket 事件流（`/ws/react/run`）

前端通过 WebSocket 接收服务端推送的事件：

| 事件类型 | 字段 | 说明 |
|---|---|---|
| `prompt_preview` | `messages: list[dict]` | 完整 Prompt 组装结果（首步前推送）|
| `step_start` | `index: int` | 开始第 N 步推理 |
| `chunk` | `index, chunk: str` | LLM 流式输出片段 |
| `step` | `index, thought, action, action_input, observation` | 单步推理完整记录 |
| `finish` | `answer: str` | 最终答案（WebSocket 随后关闭）|
| `error` | `message: str` | 推理过程中发生异常 |

### 后台提交机制

`finish` 事件发送后，WebSocket 立即关闭，用户看到答案。**commit / Embedding 写入 / 中期蒸馏 / 人格演化 / 静态 Prompt 缓存构建** 在后台线程中异步完成，不阻塞用户等待：

```
客户端收到 finish → WebSocket 关闭
                          ↓（后台线程，用户无感知）
                    post_process()
                      commit → FAISS 写入
                      persona.evolve()
                      add_turn() + consolidate()
                      build_static() → _static_cache（下轮预热）
```

---

## 前端功能

### 设置面板（左侧）

- **LLM 配置**：模型路径/名称、API Key、Base URL、参数（max_tokens、temperature、do_sample）、System Prompt
- **ReAct 配置**：语言（中/英）、最大步数、主工具列表
- **人格配置**：启用/禁用、画像编辑（姓名/背景/性格/价值观/风格）、事件日志参数
- **"Show Full Input" 开关**：展开每条用户消息，显示完整的 Prompt 组装内容（系统提示、人格块、记忆块、历史对话、当前问题）

### 消息区域

- `Enter` 发送，`Shift+Enter` 换行
- ReAct 模式下，每步展示 Thought / Action / Action Input / Observation 折叠卡片
- 开启"Show Full Input"后，用户消息卡片内嵌完整 Prompt（`prompt_preview` 事件内容）

### 对话历史

- 左侧面板显示已保存对话列表
- 切换对话时，调用 `/api/react/restore` 恢复 PromptManager 历史，保证跨页面会话连续性
