# llm_core

LLM 抽象层，屏蔽本地推理与远程 API 的差异，对上层提供统一的 `generate(prompt) -> str` 接口。

## 文件

| 文件 | 说明 |
|---|---|
| `llm.py` | `BaseLLM` / `CausalLLM` / `OpenAILLM` / `LLM` |
| `config/llm_core/config.py` | `LLMConfig` 配置 dataclass |

## 核心类

### `LLM`（统一入口）

```python
from config.llm_core.config import LLMConfig
from llm_core.llm import LLM

# API 模式（api_key 非空）
llm = LLM(LLMConfig(model="gpt-4o", api_key="sk-..."))

# 本地推理（api_key 为空字符串）
llm = LLM(LLMConfig(model="Qwen/Qwen2.5-7B-Instruct"))

result = llm.generate("你好")
```

### 路由规则

| `api_key` | 后端 |
|---|---|
| `""` | `CausalLLM`（本地 Transformer） |
| 非空字符串 | `OpenAILLM`（OpenAI 兼容 API） |

## `LLMConfig` 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `model` | 必填 | 本地路径 / HuggingFace ID / API 模型名 |
| `api_key` | `""` | 留空为本地推理 |
| `base_url` | `None` | 自定义 API 地址（vLLM、Ollama 等） |
| `max_tokens` | `512` | 最大生成 token 数 |
| `temperature` | `1.0` | 采样温度 |
| `do_sample` | `False` | 是否采样（本地推理） |
| `device` | `"auto"` | 设备（本地推理） |
| `system_prompt` | `""` | 系统提示词 |

## System Prompt 与 KV Cache

- **`CausalLLM`**：初始化时若提供 `system_prompt`，提前计算 KV Cache 并存储，后续每次 `generate()` 通过 `deepcopy` 注入，避免重复计算。
- **`OpenAILLM`**：将 `system_prompt` 作为 `{"role": "system"}` 消息头插入每次请求。
