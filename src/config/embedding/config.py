from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BuildConfig:
    csv_path: str = ""
    text_column: str = "text"
    extra_columns: list[str] = field(default_factory=list)
    chunk_size: int = 512
    chunk_overlap: int = 64
    device: str = "auto"
    model_name_or_path: str = "BAAI/bge-small-zh-v1.5"
    use_fp16: bool = True
    batch_size: int = 32
    passage_prefix: str = ""
    query_prefix: str = "query: "
    output_dir: str = ""
    collection_name: str = "corpus"
    meta_filename: str = "meta.jsonl"

    @classmethod
    def from_yaml(cls, path: str) -> BuildConfig:
        import yaml

        with open(path, encoding="utf-8") as f:
            data: dict = yaml.safe_load(f) or {}
        return cls(
            csv_path=data.get("csv_path", ""),
            text_column=data.get("text_column", "text"),
            extra_columns=list(data.get("extra_columns", [])),
            chunk_size=int(data.get("chunk_size", 512)),
            chunk_overlap=int(data.get("chunk_overlap", 64)),
            device=data.get("device", "auto"),
            model_name_or_path=data.get("model_name_or_path", "BAAI/bge-small-zh-v1.5"),
            use_fp16=bool(data.get("use_fp16", True)),
            batch_size=int(data.get("batch_size", 32)),
            passage_prefix=data.get("passage_prefix", ""),
            query_prefix=data.get("query_prefix", "query: "),
            output_dir=data.get("output_dir", ""),
            collection_name=data.get("collection_name", "corpus"),
            meta_filename=data.get("meta_filename", "meta.jsonl"),
        )
