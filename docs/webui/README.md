# webui

基于 FastAPI 的轻量 Web 聊天界面，接入 LLM 核心，支持在浏览器中配置和对话。

## 文件

| 文件 | 说明 |
|---|---|
| `app.py` | FastAPI 后端，暴露 `/api/init` 和 `/api/chat` |
| `index.html` | 单页前端，纯 HTML + Vanilla JS，无框架依赖 |
| `run.py` | 启动入口 |

## 启动

```bash
cd D:\ReAct\src\webui
pip install fastapi uvicorn
python run.py
```

访问 `http://localhost:8080`。

## API

| 路由 | 方法 | 说明 |
|---|---|---|
| `/` | GET | 返回前端 HTML |
| `/api/init` | POST | 初始化 LLM，接受完整 `LLMConfig` 参数 |
| `/api/chat` | POST | 发送消息，返回 LLM 回复 |
| `/api/status` | GET | 查询 LLM 是否已初始化 |

### `/api/init` 请求体

```json
{
    "model": "gpt-4o",
    "api_key": "sk-...",
    "base_url": null,
    "max_tokens": 512,
    "temperature": 1.0,
    "system_prompt": "你是一个有帮助的助手。"
}
```

### `/api/chat` 请求体

```json
{"prompt": "你好"}
```

## 前端功能

- 左侧配置面板：模型、API Key、Base URL、参数、System Prompt
- `api_key` 填写时标签自动切换「本地模型路径 ↔ API 模型名称」
- `Enter` 发送，`Shift+Enter` 换行
- 输入框高度自动伸缩
- 状态徽章实时显示初始化状态与模式（本地推理 / API 模式）
