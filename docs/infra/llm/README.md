# infra/llm

`src/infra/llm/` 对上提供 `BaseLLM` 的四个生成方法：

- `generate(prompt)`
- `stream_generate(prompt)`
- `generate_messages(messages)`
- `stream_generate_messages(messages)`

配置类位于 `src/config/llm_core/config.py`，默认 YAML 是 `config/llm_core/config.yaml`。

## 分层

- `llm.py`：`BaseLLM`、进程内 `CausalLLM`、OpenAI 兼容 `OpenAILLM` 与轻量 `LLM` facade。
- `handle.py`：`LLMHandle`，对现有消费者保持稳定引用。
- `service.py`：`LLMService`，选择后端、管理本地服务生命周期并更新 handle。
- `backend.py`：本地推理 manager 的 `BaseInferenceBackend` 协议。
- `transformers/manager.py`：`TransformersBackend`。
- `official/manager.py`：`OfficialVLLMManager`。
- `custom/manager.py`：`CustomVLLMManager`。

上层运行时应从 `LLMService.handle` 获取 LLM，而不是自行缓存某个具体 backend。

## LLMService 与 LLMHandle

`AppState` 在基础设施装配时创建三个本地 backend 实例，并构造：

```python
LLMService(transformers_backend, vllm_backend, clone_backend)
```

`LLMService.start(cfg, vllm_cfg=None)` 构造当前 LLM。首次启动创建一个 `LLMHandle`；后续 `start()` / `reload()` 调用 `handle.update(new_llm)`，因此 Soul、Speak、TaoLoop 等已持有的同一 handle 会自动切换到新模型。

`LLMHandle` 完整转发四个 `BaseLLM` 方法。`register_aux()`、`get_aux_llm()`、`unregister_aux()` 管理不负责 subprocess 生命周期的命名辅助模型：`register_aux()` 直接调用 `LLM(cfg)`，因此既可创建 OpenAI 兼容模型，也可在 `backend="transformers"` 时创建进程内 `CausalLLM`。未命中名称时 `get_aux_llm()` 回退到主模型。

## 四种 backend

`LLMService` 识别以下 `LLMConfig.backend`：

- `openai`：不启动本地 subprocess，直接由 `LLM(cfg)` 创建 `OpenAILLM`。可连接 OpenAI、DeepSeek 或任意 OpenAI 兼容 API。
- `transformers`：`TransformersBackend` 记录生命周期，再构造进程内 `CausalLLM`。
- `vllm`：`OfficialVLLMManager` 启动官方 `vllm serve`，然后返回指向其 `/v1` 地址的 `OpenAILLM`。
- `vllm-clone`：`CustomVLLMManager` 启动 `python -m infra.llm.custom.server`，同样以 OpenAI 兼容客户端访问。

单独使用 `LLM(cfg)` 时只有 `transformers` 会路由到 `CausalLLM`，其余值都按 OpenAI 兼容客户端处理。本地 `vllm` 与 `vllm-clone` 的 subprocess 生命周期和 `base_url` 注入必须通过 `LLMService` 完成。

## Windows 行为

`vllm` 和 `vllm-clone` 都要求 Linux 执行环境：

- Windows 检测到可用 WSL2 时，manager 将命令包装为 `wsl -- env PYTHONPATH=...`，并转换 Windows 绝对路径。
- Windows 没有可用 WSL2 时，`LLMService` 使用 `dataclasses.replace(cfg, backend="transformers")` 自动降级；`status()["degraded_reason"]` 返回原因。
- `openai` 与 `transformers` 不需要这项降级。

降级后的 `LLMService.cfg` 和 `status()["backend"]` 都是 `transformers`。

## 配置字段

`LLMConfig` 当前字段包括：

- 通用：`model`、`max_tokens`、`temperature`、`system_prompt`、`backend`
- API：`api_key`、`base_url`
- Transformers：`device`、`do_sample`、`top_p`、`top_k`、`repetition_penalty`
- 保留字段：`trained_model_path`

`CausalLLM` 把 `system_prompt` 加入 chat template；`OpenAILLM` 把它转换为请求开头的 `SystemMessage`。
