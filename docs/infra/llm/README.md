# llm_core

LLM 抽象层，屏蔽本地推理与远程 API 的差异，对上层提供统一的 `generate` / `stream_generate` 接口。

## 文件

| 文件 | 说明 |
|---|---|
| `infra/llm/llm.py` | `BaseLLM` / `CausalLLM` / `OpenAILLM` / `LLM` |
| `infra/llm/handle.py` | `LLMHandle`（可变转发封装，持有内部 LLM 实例，`update()` 支持运行时热替换）|
| `infra/llm/service.py` | `LLMService`（vLLM 服务管理）|
| `config/llm_core/config.py` | `LLMConfig` 配置 dataclass |

## 核心类

### `LLM`（统一入口）

```python
from config.llm_core.config import LLMConfig
from infra.llm import LLM

# OpenAI 兼容 API（backend="openai"，默认值）
llm = LLM(LLMConfig(model="gpt-4o", api_key="sk-...", backend="openai"))

# 本地 vLLM 服务
llm = LLM(LLMConfig(model="Qwen/Qwen2.5-7B-Instruct", base_url="http://localhost:8000/v1", backend="vllm"))

# 本地 Transformers 推理
llm = LLM(LLMConfig(model="Qwen/Qwen2.5-7B-Instruct", backend="transformers"))

result = llm.generate("你好")
```

### 路由规则

路由由 `LLMConfig.backend` 字段决定：

| `backend` | 后端 | 典型场景 |
|---|---|---|
| `"openai"`（默认）| `OpenAILLM` | OpenAI、DeepSeek、任意兼容 API |
| `"vllm"` | `OpenAILLM`（由 `LLMService` 设置 `base_url`）| 本地 vLLM 服务 |
| `"transformers"` | `CausalLLM` | 本地 HuggingFace 模型 |

## `LLMConfig` 参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `model` | `""` | 本地路径 / HuggingFace ID / API 模型名 |
| `api_key` | `""` | API Key（`backend="openai"` 时使用）|
| `base_url` | `None` | 自定义 API 地址（vLLM、Ollama 等）|
| `max_tokens` | `512` | 最大生成 token 数 |
| `temperature` | `1.0` | 采样温度 |
| `do_sample` | `False` | 是否采样（`backend="transformers"` 时有效）|
| `top_p` | `1.0` | nucleus sampling（`do_sample=True` 且 `top_p<1.0` 时生效）|
| `top_k` | `0` | top-k sampling（`do_sample=True` 且 `top_k>0` 时生效）|
| `repetition_penalty` | `1.0` | 重复惩罚系数（`backend="transformers"` 时有效）|
| `device` | `"auto"` | 推理设备（`backend="transformers"` 时有效）|
| `system_prompt` | `""` | 系统提示词 |
| `backend` | `"openai"` | 后端选择：`"openai"` / `"vllm"` / `"transformers"` |
| `trained_model_path` | `""` | 微调模型路径（保留字段，供自定义后端使用）|

从 YAML 加载：

```python
cfg = LLMConfig.from_yaml("config/llm_core/config.yaml")
```

## System Prompt

- **`CausalLLM`**：`system_prompt` 以 `{"role": "system"}` 条目插入每次 chat template 头部。
- **`OpenAILLM`**：`system_prompt` 作为 `SystemMessage` 前置到每次请求的消息列表。
