# react/memory/long_term/embedding

基于 BGE 模型的 Embedding 微服务，作为长期记忆（RAG）的向量化基础。

## 文件

| 文件 | 说明 |
|---|---|
| `service.py` | FastAPI 服务，暴露 embedding 接口 |
| `run.py` | 启动入口，接受 `EmbeddingConfig` |

## 启动

```bash
cd D:\ReAct\src\react\memory\long_term\embedding
python run.py
```

自定义配置：

```python
from config.react.memory.embedding_config import EmbeddingConfig
from react.memory.long_term.embedding.run import main

main(EmbeddingConfig(
    model_name_or_path="BAAI/bge-large-zh-v1.5",
    use_fp16=True,
    device="cuda",
    port=8000,
    workers=4,
))
```

## API 接口

### `GET /health`

检查服务与模型状态。

```json
{"status": "ok", "ready": true}
```

### `POST /embeddings/query`

对检索 query 生成向量（自动添加 `"query: "` 前缀）。

```json
// 请求
{"text": "今天天气怎么样"}

// 响应
{"embedding": [0.012, -0.034, ...]}
```

### `POST /embeddings/passage`

批量对文档生成向量（用于建库）。

```json
// 请求
{"texts": ["文档1", "文档2"]}

// 响应
{"embeddings": [[0.012, ...], [0.034, ...]]}
```

## BGE 前缀规则

BGE 系列模型通过不同前缀区分 query 和 passage，可提升检索质量：

| 用途 | 前缀 | 配置项 |
|---|---|---|
| 检索 query | `"query: "` | `query_prefix` |
| 文档入库 | `""` | `passage_prefix` |

## 状态

长期记忆模块（向量存储、检索、注入 Prompt）待完成。
