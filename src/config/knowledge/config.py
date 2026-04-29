from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(key: str, fallback: str) -> str:
    return os.environ.get(key, fallback)


@dataclass
class KnowledgeConfig:
    mysql_url: str = field(
        default_factory=lambda: _env(
            "MYSQL_URL",
            "mysql+pymysql://root:password@localhost:3306/knowledge",
        )
    )
    redis_url: str = field(
        default_factory=lambda: _env(
            "REDIS_URL",
            "redis://localhost:6379/0",
        )
    )
    qdrant_path: str = field(
        default_factory=lambda: _env(
            "QDRANT_PATH",
            ".react/knowledge_base/qdrant",
        )
    )
    collection_name: str = "knowledge"

    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    device: str = "auto"
    passage_prefix: str = ""
    query_prefix: str = "query: "
    use_fp16: bool = True
    batch_size: int = 32

    top_k: int = 5
    cache_ttl: int = 300

    chunk_size: int = 512
    chunk_overlap: int = 64

    @classmethod
    def from_yaml(cls, path: str) -> KnowledgeConfig:
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, d: dict) -> KnowledgeConfig:
        return cls(
            mysql_url=d.get("mysql_url") or _env(
                "MYSQL_URL",
                "mysql+pymysql://root:password@localhost:3306/knowledge",
            ),
            redis_url=d.get("redis_url") or _env(
                "REDIS_URL",
                "redis://localhost:6379/0",
            ),
            qdrant_path=d.get("qdrant_path") or _env(
                "QDRANT_PATH",
                ".react/knowledge_base/qdrant",
            ),
            collection_name=d.get("collection_name", "knowledge"),
            embedding_model=d.get("embedding_model", "BAAI/bge-small-zh-v1.5"),
            device=d.get("device", "auto"),
            passage_prefix=d.get("passage_prefix", ""),
            query_prefix=d.get("query_prefix", "query: "),
            use_fp16=bool(d.get("use_fp16", True)),
            batch_size=int(d.get("batch_size", 32)),
            top_k=int(d.get("top_k", 5)),
            cache_ttl=int(d.get("cache_ttl", 300)),
            chunk_size=int(d.get("chunk_size", 512)),
            chunk_overlap=int(d.get("chunk_overlap", 64)),
        )
