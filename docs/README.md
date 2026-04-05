# ReAct 项目总览

基于 ReAct（Reasoning + Acting）范式的智能体框架，支持本地 Transformer 推理与 OpenAI 兼容 API，集成多层记忆系统与可扩展动作空间。

## 项目结构

```
src/
├── config/                  # 所有模块的配置 dataclass
│   ├── llm_core/            # LLM 核心配置
│   └── react/memory/        # 记忆模块配置
├── llm_core/                # LLM 抽象层
├── react/                   # ReAct 顶层循环及子模块
│   ├── action/              # 动作空间
│   ├── memory/              # 三级记忆系统
│   ├── prompt/              # 提示构造器
│   ├── loop.py              # 顶层 ReAct 循环
│   └── parser.py            # LLM 输出解析
├── webui/                   # Web 前端（FastAPI + HTML）
└── test/                    # 测试
```

## 已完成模块

| 模块 | 状态 | 说明 |
|---|---|---|
| `llm_core` | 完成 | 本地推理 + OpenAI API 双后端 |
| `react/action` | 完成 | 动作注册与执行，JSON 输入 |
| `react/memory/short_term` | 完成 | Token 级滑动窗口短期记忆 |
| `react/memory/medium_term` | 完成 | 滚动摘要中期记忆 |
| `react/memory/long_term` | 进行中 | BGE Embedding 服务（RAG 基础） |
| `react/prompt` | 完成 | ReAct 标准 Prompt 构造 |
| `react/loop` | 完成 | ReAct 顶层推理循环 |
| `webui` | 完成 | 聊天 Web 界面 |

## 快速开始

```python
from config.llm_core.config import LLMConfig
from llm_core.llm import LLM
from react.action.executor import ActionExecutor
from react.action.tools import WeatherAction
from react import ReActLoop

llm = LLM(LLMConfig(model="gpt-4o", api_key="sk-..."))
executor = ActionExecutor()
executor.register(WeatherAction)

loop = ReActLoop(
    llm=llm,
    executor=executor,
    tool_descriptions={"weather": "查询天气"},
    max_steps=5,
)
print(loop.run("今天天气怎么样？"))
```

## 子模块文档

- [llm_core](./llm_core/README.md)
- [config](./config/README.md)
- [react/action](./react/action/README.md)
- [react/memory](./react/memory/README.md)
- [react/prompt](./react/prompt/README.md)
- [webui](./webui/README.md)
