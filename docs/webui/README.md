# WebUI

基于 FastAPI 的轻量 Web 聊天界面，支持普通对话与 ReAct 推理两种模式，在浏览器中配置、对话、管理知识库并使用语音功能。

## 文件

| 文件 | 说明 |
|---|---|
| `src/webui/app.py` | FastAPI 后端，REST API + WebSocket 流式接口 |
| `src/webui/index.html` | 单页前端，纯 HTML + Vanilla JS，无框架依赖 |
| `src/webui/run.py` | 启动入口 |

## 启动

```bash
# 项目根目录
python src/run.py
# 或直接
python src/webui/run.py
```

访问 `http://localhost:8300`。也可通过 `start.bat` 一键启动（含 Docker 数据库、依赖检查、浏览器自动打开）。

---

## API

### LLM 管理

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/config` | GET | 读取当前 LLM 配置 |
| `/api/config/save` | POST | 保存 LLM 配置到 YAML |
| `/api/init` | POST | 初始化 / 切换 Chat 模式 LLM |
| `/api/status` | GET | 查询 LLM 初始化状态与 ReAct 会话状态 |

### 普通对话

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/chat` | POST | SSE 流式对话（纯文本，带多轮 history）|
| `/ws/chat` | WebSocket | WebSocket 流式对话（同上）|

### ReAct 推理

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/react/init` | POST | 初始化 ReAct 会话（语言、工具、步数等）|
| `/api/react/run` | POST | SSE 流式 ReAct 推理 |
| `/ws/react/run` | WebSocket | WebSocket 流式 ReAct 推理（主路径）|
| `/api/react/reset` | POST | 清空当前会话历史 |
| `/api/react/restore` | POST | 从保存的对话 JSON 恢复会话历史 |
| `/api/react/status` | GET | 查询 ReAct 初始化状态 |
| `/api/react/memory/clear` | POST | 清除记忆 |
| `/api/react/tools` | GET | 查询已注册工具列表（按分类）|
| `/api/react/tools/search` | GET | 语义搜索工具 |

### 对话历史

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/history` | GET | 列出所有已保存对话 |
| `/api/history/{id}` | GET | 读取单条对话 |
| `/api/history` | POST | 保存对话 |
| `/api/history/{id}` | DELETE | 删除对话 |
| `/api/history` | DELETE | 删除全部历史 |

### 人格（Persona）

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/persona` | GET | 读取人格配置（画像 + 配置项）|
| `/api/persona/save` | POST | 保存人格配置 |

### 记忆（Memory）

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/memory` | GET | 读取记忆配置 |
| `/api/memory/save` | POST | 保存记忆配置 |
| `/api/memory/consolidate` | POST | 手动触发中期记忆蒸馏 |

### 知识库（Knowledge Base）

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/kb/documents` | GET | 列出所有文档 |
| `/api/kb/documents/{doc_id}` | DELETE | 删除指定文档 |
| `/api/kb/search` | GET | 检索知识库，支持 `mode` 参数 |
| `/api/kb/ingest` | POST | 写入新文档 |
| `/api/kb/repair` | POST | 修复未向量化的 chunks |

#### `/api/kb/search` 参数

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `q` | str | 必填 | 查询文本 |
| `top_k` | int | 5 | keyword / semantic 模式返回条数 |
| `top_k_each` | int | 3 | hybrid 模式每路返回条数 |
| `mode` | str | `"hybrid"` | `keyword` / `semantic` / `hybrid` |

响应示例：

```json
{
  "query": "量子纠缠",
  "mode": "hybrid",
  "results": [
    {
      "chunk_id": "...",
      "doc_id": "...",
      "score": 0.92,
      "source": "manual",
      "content": "量子纠缠是...",
      "meta": {"domain": "physics"}
    }
  ]
}
```

### TTS / STT

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/tts/config` | GET | 读取 TTS 配置 |
| `/api/tts/config/save` | POST | 保存 TTS 配置 |
| `/api/tts/synthesize` | POST | 一次性合成音频 |
| `/api/tts/download` | GET | 下载已合成的音频文件 |
| `/ws/tts` | WebSocket | 流式 TTS（推送音频 chunk）|
| `/api/stt/config` | GET | 读取 STT 配置 |
| `/api/stt/config/save` | POST | 保存 STT 配置 |
| `/api/stt/transcribe` | POST | 上传音频，返回转录文本 |
| `/api/stt/download` | GET | 下载本地 STT 模型 |
| `/ws/stt` | WebSocket | 实时 STT |

---

## WebSocket 事件流（`/ws/react/run`）

| 事件类型 | 字段 | 说明 |
|---|---|---|
| `prompt_preview` | `messages: list[dict]` | 完整 Prompt 组装结果（首步前推送）|
| `step_start` | `index: int` | 开始第 N 步推理 |
| `chunk` | `index, chunk: str` | LLM 流式输出片段 |
| `step` | `index, thought, action, action_input, observation` | 单步推理完整记录 |
| `finish` | `answer: str` | 最终答案（WebSocket 随后关闭）|
| `error` | `message: str` | 推理过程中发生异常 |

### 后台提交机制

`finish` 事件发送后 WebSocket 立即关闭，commit / 向量写入 / 蒸馏 / 人格演化 / 静态 Prompt 缓存构建在后台线程异步完成：

```
客户端收到 finish → WebSocket 关闭
                          ↓（后台线程）
                    post_process()
                      commit → FAISS 写入
                      persona.evolve()
                      add_turn() + consolidate()
                      build_static()
```

---

## 前端布局

### 主区域切换

`#s-workspace` 下两个面板互斥显示（通过 `.hidden` 切换）：

| 元素 ID | 内容 | 入口 |
|---|---|---|
| `#main-area` | 聊天区（默认） | 知识库面板点击"← 返回聊天" |
| `#kb-panel` | 知识库独立面板 | 侧边栏 📚 按钮 |

### 知识库独立面板（`#kb-panel`）

点击侧边栏 📚 按钮进入，与聊天区完全隔离：

- **搜索区**：搜索框 + 模式下拉（`hybrid` / `semantic` / `keyword`）+ 搜索结果列表
- **写入区**：内容 / 标题 / 领域 / 概念输入框 + 写入按钮
- **文档列表**：列出所有文档，每行可删除；[修复索引] 按钮触发 `/api/kb/repair`

### Settings Modal（设置面板）

Settings 按钮（⚙）打开模态框，包含以下 Tab：

| Tab | 说明 |
|---|---|
| **Core** | 模型配置（API Key / Base URL / 参数）+ ReAct Agent 配置（Agent 开关 / Prompt Language / Max Steps） |
| **🧠 Memory** | L1 短期记忆 / L2 中期记忆 / L3 长期记忆 / Milestone 参数 |
| **🎭 Persona** | 人格开关、画像编辑（姓名 / 背景 / 性格 / 价值观 / 风格）、演化引擎参数 |
| **🔊 Voice** | TTS 提供商 / 语音名称 / 语速 / 音量；STT 提供商 / 语言 / 模型 |

> 知识库已从 Settings 中独立，移至侧边栏 📚 面板。

### 消息区域

- `Enter` 发送，`Shift+Enter` 换行
- ReAct 模式下每步显示 Thought / Action / Action Input / Observation 折叠卡片
- "Show Full Input" 开关：在用户消息下方展示完整 Prompt 组装内容

### 侧边栏

- 显示对话历史列表，支持切换/删除
- 顶栏按钮：新建对话（＋）、清空历史（🗑）、知识库（📚）、设置（⚙）
- 切换对话时调用 `/api/react/restore` 恢复会话历史
