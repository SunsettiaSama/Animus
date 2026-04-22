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
| `react/action` | 完成 | 工具注册、Pydantic 参数校验、执行调度 |
| `react/memory/short_term` | 完成 | Token 级滑动窗口短期记忆 |
| `react/memory/medium_term` | 完成 | 滚动摘要中期记忆（LLM 蒸馏） |
| `react/memory/long_term` | 完成 | BGE Embedding + FAISS + RAG，跨会话持久化 |
| `react/prompt` | 完成 | 块驱动 Prompt 组装 + 静态缓存预热（`StaticPromptParts`）|
| `react/persona` | 完成 | 人物画像 + 事件演化日志 |
| `react/trace` | 完成 | 推理链存档（`.react/traces/`）|
| `react/loop` | 完成 | 两层循环（ConvLoop + TaoLoop）+ 异步后台提交 |
| `webui` | 完成 | ReAct + 普通对话双模式，含完整 Prompt 预览、人格配置 |
| `test` | 完成 | 记忆模块 17 用例 + 工具 Pydantic 校验测试 |

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
- [react/](./react/README.md) — 完整链路（两层循环、记忆、Prompt、Persona、Trace）
- [react/action](./react/action/README.md) — 工具注册与 Pydantic 校验
- [react/memory](./react/memory/README.md) — 三级记忆系统
- [react/prompt](./react/prompt/README.md) — 块驱动 Prompt 组装
- [webui](./webui/README.md) — Web 界面与 API
- [test](./test/README.md) — 测试覆盖说明
