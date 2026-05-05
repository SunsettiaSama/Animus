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

    @classmethod
    def from_yaml(cls, path: str) -> EmbeddingConfig:
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls(
            model_name_or_path=data.get("model_name_or_path", "BAAI/bge-small-zh-v1.5"),
            use_fp16=bool(data.get("use_fp16", True)),
            device=data.get("device", "auto"),
            query_prefix=data.get("query_prefix", "query: "),
            passage_prefix=data.get("passage_prefix", ""),
            host=data.get("host", "0.0.0.0"),
            port=int(data.get("port", 8000)),
            workers=int(data.get("workers", 1)),
        )
