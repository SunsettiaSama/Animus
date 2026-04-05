from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EmbeddingConfig:
    model_name_or_path: str = "BAAI/bge-small-zh-v1.5"
    use_fp16: bool = True
    device: str = "auto"
    query_prefix: str = "query: "
    passage_prefix: str = ""
    host: str = "0.0.0.0"
    port: int = 8000
    workers: int = 1
